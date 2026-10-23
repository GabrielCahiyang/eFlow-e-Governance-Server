"""Decode Kitten-TTS 2's own S3 tokens on CUDA, in an isolated process."""
import json
from pathlib import Path
import sys
import time
import wave
import gc
import torch

def load_decoder(asset_root):
    if not torch.cuda.is_available():
        raise RuntimeError('CUDA speech decoder is unavailable')
    torch.set_num_threads(2)
    torch.backends.cudnn.benchmark = False
    torch.backends.cudnn.enabled = True
    torch._C._jit_set_profiling_executor(False)
    torch._C._jit_set_profiling_mode(False)
    # Loading TorchScript and importing torch are the expensive cold steps.
    # Preload on CPU without taking VRAM away from the shared inference queue.
    device = torch.device('cpu')
    module = torch.jit.load(str(Path(asset_root) / 'decoder.pt'), map_location=device).eval()
    with (Path(asset_root) / 'voices.json').open(encoding='utf-8') as source:
        voice = json.load(source)['Bruno']
    return module, voice, device

def move_decoder(loaded, target):
    module, voice, current = loaded
    device = torch.device(target)
    if current == device:
        return loaded
    module.to(device)
    # The vendor traced this graph on CPU: map_location moves parameters but
    # leaves explicit device constants in the graph. Move those too.
    device_constants = 0
    for part in module.modules():
        for name in part._c._method_names():
            graph = part._c._get_method(name).graph
            for node in graph.findAllNodes('prim::Constant', recurse=True):
                # This exported decoder is frozen: many weights are graph
                # constants, not parameters. module.to() alone leaves these
                # behind and fails with mixed CPU/CUDA tensors.
                if node.hasAttribute('value') and node.kindOf('value') == 't':
                    node.t_('value', node.t('value').to(device))
                if node.hasAttribute('value') and node.kindOf('value') == 's' and str(node.output().type()) == 'Device':
                    if node.s('value') in ('cpu', 'cuda', 'cuda:0'):
                        node.s_('value', str(device))
                        device_constants += 1
    if device.type == 'cpu':
        gc.collect()
        torch.cuda.empty_cache()
    return module, voice, device

def decode(report_path, asset_root, output, loaded=None):
    module, voice, device = move_decoder(loaded or load_decoder(asset_root), 'cuda:0')
    report = json.loads(Path(report_path).read_text(encoding='utf-8'))
    waves = []
    started = time.monotonic()
    with torch.inference_mode(), torch.jit.optimized_execution(False):
        for chunk in report['chunks']:
            ids = chunk['audio_tokens']
            if not ids or not chunk['terminated']:
                raise RuntimeError('The speech model did not finish its turn')
            result = module(
                torch.tensor([ids + [4299] * 3], dtype=torch.long, device=device),
                torch.tensor(voice['prompt_token'], dtype=torch.long, device=device),
                torch.tensor(voice['prompt_feat'], dtype=torch.float32, device=device),
                torch.tensor(voice['embedding'], dtype=torch.float32, device=device),
            ).flatten()
            if not torch.isfinite(result).all().item():
                raise RuntimeError('Speech contains invalid samples')
            if waves:
                waves.append(torch.zeros(3840, device=device))
            waves.append(result)
        audio = torch.cat(waves)
        if audio.numel() > 24_000 * 60 or audio.abs().max().item() < .00001:
            raise RuntimeError('Speech duration or volume is invalid')
        pcm = (audio.clamp(-1, 1) * 32767).to(torch.int16).cpu().numpy().tobytes()
    with wave.open(str(output), 'wb') as target:
        target.setnchannels(1); target.setsampwidth(2); target.setframerate(24_000)
        target.writeframes(pcm)
    return {'decoder': 'Kitten-TTS 2 student_w4', 'device': str(device), 'seconds': time.monotonic() - started, 'audio_seconds': audio.numel() / 24_000}

if __name__ == '__main__':
    if sys.argv[1] == '--worker':
        assets = sys.argv[2]
        loaded = load_decoder(assets)
        print(json.dumps({'ready': True}), flush=True)
        for line in sys.stdin:
            try:
                request = json.loads(line)
                if request.get('operation') == 'release':
                    loaded = move_decoder(loaded, 'cpu')
                    result = {'released': True, 'allocated_bytes': torch.cuda.memory_allocated()}
                else:
                    loaded = move_decoder(loaded, 'cuda:0')
                    result = decode(request['report'], assets, request['output'], loaded)
                    # Keep weights, release transient waveform/attention buffers
                    # before Qwen or Kitten's token model takes the next turn.
                    torch.cuda.empty_cache()
                print(json.dumps(result), flush=True)
            except Exception:
                import traceback
                traceback.print_exc(file=sys.stderr)
                print(json.dumps({'error': 'Speech decoding failed'}), flush=True)
    else:
        print(json.dumps(decode(*sys.argv[1:])), flush=True)

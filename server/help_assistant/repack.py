"""Lossless TQ2_1 -> standard Q4_0 or F16 storage for compatible kernels.

Uses the published KittenML GGML block layout: two half scales and 64 packed
ternary bytes per 256 weights. Q4_0 stores exactly the same -scale/0/+scale
values, with the original half scale repeated for each 32-weight block.
F16 expands those same ternary values for the production CUDA runtime.
This changes storage, not checkpoint values. No training or rounding is used.
"""
import hashlib
import math
from pathlib import Path
import struct
import numpy as np

def repack_blocks(data):
    source = np.frombuffer(data, dtype=np.uint8).reshape(-1, 68)
    output = np.empty((len(source), 8, 18), dtype=np.uint8)
    reconstructed = np.zeros((len(source), 64), dtype=np.uint8)
    for group in range(2):
        codes = source[:, group * 32:(group + 1) * 32]
        for layer in range(4):
            ternary = (codes >> (2 * layer)) & 3
            if np.any(ternary > 2):
                raise ValueError('Source contains values outside the documented ternary format')
            index = group * 4 + layer
            output[:, index, :2] = source[:, 64 + group * 2:66 + group * 2]
            q = ternary + 7
            output[:, index, 2:] = q[:, :16] | (q[:, 16:] << 4)
            restored = np.concatenate((output[:, index, 2:] & 15, output[:, index, 2:] >> 4), axis=1) - 7
            reconstructed[:, group * 32:(group + 1) * 32] |= restored << (2 * layer)
    if not np.array_equal(reconstructed, source[:, :64]):
        raise ValueError('Ternary storage round trip failed')
    return output.tobytes()

def fp16_blocks(data):
    source = np.frombuffer(data, dtype=np.uint8).reshape(-1, 68)
    scales = source[:, 64:].copy().view(np.float16)
    output = np.empty((len(source), 2, 4, 32), dtype=np.float16)
    for group in range(2):
        for layer in range(4):
            codes = ((source[:, group * 32:(group + 1) * 32] >> (layer * 2)) & 3).astype(np.int16)
            if np.any(codes > 2):
                raise ValueError('Invalid ternary weight')
            output[:, group, layer] = (codes - 1) * scales[:, group, None]
    if not np.isfinite(output).all():
        raise ValueError('Non-finite checkpoint weights')
    return output.tobytes()

def repack_gguf(source_path, destination, storage='q4'):
    if storage not in ('q4', 'f16'):
        raise ValueError('Unsupported output storage')
    converted_type = 1 if storage == 'f16' else 2
    source_path, destination = Path(source_path), Path(destination)
    with source_path.open('rb') as source:
        def number(code):
            return struct.unpack('<' + code, source.read(struct.calcsize('<' + code)))[0]
        def string():
            return source.read(number('Q'))
        def skip(kind):
            sizes = {0: 1, 1: 1, 2: 2, 3: 2, 4: 4, 5: 4, 6: 4, 7: 1, 10: 8, 11: 8, 12: 8}
            if kind in sizes:
                source.seek(sizes[kind], 1)
            elif kind == 8:
                source.seek(number('Q'), 1)
            elif kind == 9:
                subtype, count = number('I'), number('Q')
                for _ in range(count): skip(subtype)
            else:
                raise ValueError('Unsupported GGUF metadata type')
        if source.read(4) != b'GGUF' or number('I') != 3:
            raise ValueError('Expected GGUF version 3')
        count, metadata_count = number('Q'), number('Q')
        alignment, file_type_at = 32, None
        for _ in range(metadata_count):
            key, kind = string(), number('I')
            if key == b'general.file_type' and kind == 4:
                file_type_at = source.tell()
            if key == b'general.alignment' and kind == 4:
                alignment = number('I')
            else:
                skip(kind)
        metadata_end = source.tell()
        tensors, offset = [], 0
        for _ in range(count):
            name, dimensions = string(), number('I')
            shape = [number('Q') for _ in range(dimensions)]
            kind, old_offset = number('I'), number('Q')
            size = math.prod(shape)
            if kind in (0, 1):
                old_size = new_size = size * (4 if kind == 0 else 2)
            else:
                if size % 256: raise ValueError('Unexpected quantized tensor shape')
                old_size, new_size = size // 256 * 68, size * 2 if storage == 'f16' else size // 32 * 18
            tensors.append((name, shape, kind, old_offset, old_size, offset, new_size))
            offset = (offset + new_size + alignment - 1) // alignment * alignment
        data_at = (source.tell() + alignment - 1) // alignment * alignment
        # The official bundle has only F32, F16 and one custom TQ2_1 type.
        types = {tensor[2] for tensor in tensors} - {0, 1}
        if len(types) != 1: raise ValueError('Expected one custom ternary tensor type')
        source.seek(0); metadata = bytearray(source.read(metadata_end))
        if file_type_at is not None: struct.pack_into('<I', metadata, file_type_at, converted_type)
        temporary = destination.with_suffix('.tmp')
        destination.parent.mkdir(parents=True, exist_ok=True)
        try:
            with temporary.open('wb') as target:
                target.write(metadata)
                for name, shape, kind, _, _, new_offset, _ in tensors:
                    target.write(struct.pack('<Q', len(name)) + name + struct.pack('<I', len(shape)))
                    target.write(struct.pack('<' + 'Q' * len(shape), *shape))
                    target.write(struct.pack('<IQ', kind if kind in (0, 1) else converted_type, new_offset))
                new_data = (target.tell() + alignment - 1) // alignment * alignment
                target.write(bytes(new_data - target.tell()))
                for _, _, kind, old_offset, old_size, new_offset, new_size in tensors:
                    source.seek(data_at + old_offset); target.seek(new_data + new_offset)
                    remaining = old_size
                    while remaining:
                        amount = min(remaining, 68 * 16384 if kind not in (0, 1) else 1024 * 1024)
                        block = source.read(amount)
                        if len(block) != amount: raise ValueError('Truncated source tensor')
                        target.write((fp16_blocks(block) if storage == 'f16' else repack_blocks(block)) if kind not in (0, 1) else block)
                        remaining -= amount
                    if target.tell() != new_data + new_offset + new_size:
                        raise ValueError('Tensor size mismatch')
            temporary.replace(destination)
        finally:
            temporary.unlink(missing_ok=True)
    with source_path.open('rb') as original, destination.open('rb') as converted:
        hashes = {'source_sha256': hashlib.file_digest(original, 'sha256').hexdigest(), 'output_sha256': hashlib.file_digest(converted, 'sha256').hexdigest()}
    return {**hashes, 'converted_tensors': sum(tensor[2] not in (0, 1) for tensor in tensors), 'values': 'lossless ternary round-trip checked for every block'}

if __name__ == '__main__':
    import json, sys
    print(json.dumps(repack_gguf(sys.argv[1], sys.argv[2], sys.argv[3] if len(sys.argv) > 3 else 'q4'), indent=2))

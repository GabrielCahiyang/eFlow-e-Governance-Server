import asyncio, io, json, time, wave
from array import array
from pathlib import Path
from help_assistant.parakeet_runtime import ParakeetRuntime
async def main():
 runtime=ParakeetRuntime(); receipts=[]
 source=Path('server/help-voice-test-roundtrip-1.wav')
 with wave.open(str(source)) as wav:
  rate=wav.getframerate(); samples=array('h', wav.readframes(wav.getnframes()))
 pcm=array('h',(samples[min(len(samples)-1,int(i*rate/16000))] for i in range(int(len(samples)*16000/rate))))
 try:
  for seconds in [2,3.48,3.48]:
   output=io.BytesIO()
   with wave.open(output,'wb') as wav:
    wav.setnchannels(1); wav.setsampwidth(2); wav.setframerate(16000); wav.writeframes(pcm[:int(seconds*16000)].tobytes())
   start=time.monotonic(); result=await runtime.transcribe(output.getvalue())
   receipts.append({'clip_seconds':seconds,'seconds':round(time.monotonic()-start,3),'text':result['text'],'process_pid':runtime.process.pid})
   print(json.dumps(receipts[-1]),flush=True)
 finally:
  await runtime.close()
 Path('server/help-progressive-asr-benchmark.json').write_text(json.dumps(receipts,indent=2))
asyncio.run(main())

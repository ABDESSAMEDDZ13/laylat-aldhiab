class PCMRecorder extends AudioWorkletProcessor {
  constructor(){super();this.phase=0;this.sum=0;this.count=0;this.frame=new Int16Array(320);this.pos=0;}
  process(inputs){const ch=inputs[0]?.[0];if(!ch)return true;for(let i=0;i<ch.length;i++){this.sum+=ch[i];this.count++;this.phase+=16000;if(this.phase>=sampleRate){this.phase-=sampleRate;let x=Math.max(-1,Math.min(1,this.sum/this.count));this.sum=0;this.count=0;this.frame[this.pos++]=x<0?x*32768:x*32767;if(this.pos===320){const b=this.frame.buffer;this.port.postMessage(b,[b]);this.frame=new Int16Array(320);this.pos=0;}}}return true;}
}registerProcessor('pcm-recorder',PCMRecorder);

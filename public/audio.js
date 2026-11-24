// 16 kHz signed PCM, 20 ms frames. Server enforces every sender and recipient.
export class GameAudio {
  constructor(send){this.send=send;this.ctx=null;this.stream=null;this.node=null;this.enabled=false;this.allowed=false;this.muted=false;this.next=new Map();this.sources=new Set();this.epoch=0;}
  async setup(){
    if(this.enabled){await this.ctx.resume();return;}
    if(!navigator.mediaDevices?.getUserMedia || !window.AudioContext) throw Error('الصوت يحتاج متصفحاً حديثاً واتصال HTTPS');
    if(!this.ctx)this.ctx=new AudioContext({latencyHint:'interactive'});
    await this.ctx.resume();
    try{this.stream=await navigator.mediaDevices.getUserMedia({audio:{echoCancellation:true,noiseSuppression:true,autoGainControl:true},video:false});
    await this.ctx.audioWorklet.addModule('/static/recorder.js');
    this.node=new AudioWorkletNode(this.ctx,'pcm-recorder');this.node.port.onmessage=e=>{if(this.allowed&&this.enabled&&!this.muted)this.send(e.data)};
    const src=this.ctx.createMediaStreamSource(this.stream);const mute=this.ctx.createGain();mute.gain.value=0;src.connect(this.node).connect(mute).connect(this.ctx.destination);this.enabled=true;this.setAllowed(this.allowed);
    }catch(e){this.stream?.getTracks().forEach(t=>t.stop());this.stream=null;throw e;}
  }
  setAllowed(v){this.allowed=v;this.stream?.getAudioTracks().forEach(t=>t.enabled=v&&!this.muted);}
  setMuted(v){this.muted=v;this.setAllowed(this.allowed);}
  clear(){this.epoch++;for(const s of this.sources){try{s.stop()}catch{}}this.sources.clear();this.next.clear();}
  play(buffer){if(!this.enabled||this.ctx.state!=='running'||buffer.byteLength!==648)return;const bytes=new Uint8Array(buffer,0,8);const id=Array.from(bytes,x=>x.toString(16).padStart(2,'0')).join('');const pcm=new Int16Array(buffer,8);const b=this.ctx.createBuffer(1,pcm.length,16000);const f=b.getChannelData(0);for(let i=0;i<pcm.length;i++)f[i]=pcm[i]/32768;const s=this.ctx.createBufferSource();s.buffer=b;s.connect(this.ctx.destination);let at=this.next.get(id)||0;const n=this.ctx.currentTime;if(at<n||at>n+.30)at=n+.05;s.start(at);this.next.set(id,at+.02);this.sources.add(s);s.onended=()=>this.sources.delete(s);}
}

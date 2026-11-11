"""Run the production PCM queue against bounded fake Android media endpoints."""
from pathlib import Path
import subprocess
import tempfile

ROOT = Path(__file__).resolve().parents[1]
PLAYER = ROOT / "android/java/com/wmmt/port/ArcadeBgm.java"
STUBS = {
    "AudioAttributes": """
public class AudioAttributes {
 public static final int USAGE_GAME=14, CONTENT_TYPE_MUSIC=2;
 public static class Builder {
  public Builder setUsage(int n){return this;}
  public Builder setContentType(int n){return this;}
  public AudioAttributes build(){return new AudioAttributes();}
 }
}""",
    "AudioFormat": """
public class AudioFormat {
 public static final int CHANNEL_OUT_MONO=4, CHANNEL_OUT_STEREO=12, ENCODING_PCM_16BIT=2;
 public static class Builder {
  public Builder setChannelMask(int n){return this;}
  public Builder setEncoding(int n){return this;}
  public Builder setSampleRate(int n){return this;}
  public AudioFormat build(){return new AudioFormat();}
 }
}""",
    "MediaFormat": """
public class MediaFormat {
 public static final String KEY_MIME="mime", KEY_SAMPLE_RATE="rate", KEY_CHANNEL_COUNT="channels",
  KEY_DURATION="duration", KEY_ENCODER_DELAY="delay", KEY_PCM_ENCODING="encoding";
 public String getString(String k){return "audio/mp4a-latm";}
 public int getInteger(String k){return k.equals(KEY_SAMPLE_RATE)?8000:2;}
 public long getLong(String k){return 750L;} // six source frames, of which two are encoder delay
 public boolean containsKey(String k){return true;}
 public void setInteger(String k,int n){}
}""",
    "MediaExtractor": """
import java.nio.ByteBuffer;
public class MediaExtractor {
 private boolean end;
 public void setDataSource(String p){}
 public int getTrackCount(){return 1;}
 public MediaFormat getTrackFormat(int n){return new MediaFormat();}
 public void selectTrack(int n){}
 public int readSampleData(ByteBuffer b,int o){return end?-1:1;}
 public long getSampleTime(){return 0;}
 public boolean advance(){end=true;return false;}
 public void release(){}
}""",
    "MediaCodec": """
import java.nio.ByteBuffer;
public class MediaCodec {
 public static final int BUFFER_FLAG_END_OF_STREAM=4,BUFFER_FLAG_CODEC_CONFIG=2,INFO_OUTPUT_FORMAT_CHANGED=-2;
 public static volatile int starts;
 private int phase;
 public static class BufferInfo { public int size,flags,offset; }
 public static MediaCodec createDecoderByType(String s){return new MediaCodec();}
 public void configure(MediaFormat f,Object a,Object b,int flags){}
 public void start(){starts++;}
 public int dequeueInputBuffer(long t){return 0;}
 public ByteBuffer getInputBuffer(int i){return ByteBuffer.allocate(20);}
 public void queueInputBuffer(int i,int o,int n,long t,int f){}
 public int dequeueOutputBuffer(BufferInfo b,long t){
  if(phase++==0)return INFO_OUTPUT_FORMAT_CHANGED;
  b.offset=0;b.size=20;b.flags=BUFFER_FLAG_END_OF_STREAM;return 0;
 }
 public MediaFormat getOutputFormat(){return new MediaFormat();}
 public ByteBuffer getOutputBuffer(int i){
  // The codec has already trimmed the head. The last four bytes are encoder tail.
  return ByteBuffer.wrap(new byte[]{1,1,1,1,2,2,2,2,3,3,3,3,4,4,4,4,99,99,99,99});
 }
 public void releaseOutputBuffer(int i,boolean b){}
 public void release(){}
}""",
    "AudioTrack": """
import java.nio.ByteBuffer;
public class AudioTrack {
 public static final int MODE_STREAM=1,STATE_INITIALIZED=1,WRITE_NON_BLOCKING=1;
 public static volatile int count,bytes,plays,pauses,releases,rate;
 public static final byte[] written=new byte[256];
 private boolean playing;
 public static int getMinBufferSize(int a,int b,int c){rate=a;return 16;}
 public static class Builder {
  public Builder setAudioAttributes(AudioAttributes a){return this;}
  public Builder setAudioFormat(AudioFormat a){return this;}
  public Builder setTransferMode(int a){return this;}
  public Builder setBufferSizeInBytes(int a){return this;}
  public AudioTrack build(){count++;return new AudioTrack();}
 }
 public int getState(){return STATE_INITIALIZED;}
 public void setVolume(float f){}
 public void play(){playing=true;plays++;}
 public void pause(){playing=false;pauses++;}
 public int write(ByteBuffer b,int count,int mode){
  // Actual stopped queue capacity can differ from the requested size.
  int n=Math.min(count,playing?written.length-bytes:24-bytes);
  b.get(written,bytes,n);bytes+=n;return n;
 }
 public void release(){releases++;}
}""",
}

HARNESS = """
package com.wmmt.port;
import android.media.AudioTrack;
import android.media.MediaCodec;
import java.io.File;
import java.nio.ByteBuffer;
import java.nio.ByteOrder;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.util.concurrent.CountDownLatch;
import java.util.concurrent.TimeUnit;
import java.util.concurrent.atomic.AtomicReference;
import java.util.function.BooleanSupplier;

public class ArcadeBgmPcmTest {
 private static void check(boolean ok){if(!ok)throw new AssertionError();}
 private static void await(BooleanSupplier condition) throws Exception {
  long until=System.nanoTime()+TimeUnit.SECONDS.toNanos(3);
  while(!condition.getAsBoolean() && System.nanoTime()<until)Thread.sleep(1);
  check(condition.getAsBoolean());
 }
 public static void main(String[] args) throws Exception {
  File temp=new File(args[0]);
  CountDownLatch ready=new CountDownLatch(1);
  AtomicReference<Exception> failure=new AtomicReference<>();
  check(ArcadeBgm.playableFrames("wm3DX_P_race_01",44100,
            (10710800L+1024)*1000000L/44100,1024)==10710800);
  check(ArcadeBgm.playableFrames("wm2_01",8000,750,2)==4);
  ArcadeBgm player=new ArcadeBgm(new File(temp,"wm2_01.m4a"),temp,new ArcadeBgm.Listener(){
    public void ready(ArcadeBgm b){ready.countDown();}
    public void failed(ArcadeBgm b,Exception e){failure.set(e);ready.countDown();}
  });
  player.start();
  try {
   check(ready.await(3,TimeUnit.SECONDS));
   check(failure.get()==null && AudioTrack.bytes==24 && AudioTrack.plays==0);
   player.playback(true,.5f);
   await(()->AudioTrack.bytes==AudioTrack.written.length);
   for(int i=0;i<AudioTrack.written.length;i++)check(AudioTrack.written[i]==1+(i/4)%4);
   check(AudioTrack.count==1 && MediaCodec.starts==1 && AudioTrack.plays==1);
   player.playback(false,.5f);await(()->AudioTrack.pauses==1);
   player.playback(true,.5f);await(()->AudioTrack.plays==2);
  } finally {player.close();}
  await(()->AudioTrack.releases==1);
  check(failure.get()==null && temp.list().length==0);
  File bank=new File(temp,"ten-bgm.bin");
  ByteBuffer pcm=ByteBuffer.allocate(8+38*(16+8)).order(ByteOrder.LITTLE_ENDIAN);
  pcm.putInt(0x31425457).putInt(38);
  for(int i=0;i<38;++i){
   String name=i==1?"ten_a2":"ten_xx";
   pcm.put(name.getBytes(StandardCharsets.US_ASCII)).putShort((short)0).putInt(28000).putInt(8);
  }
  for(int i=0;i<38;++i)pcm.putInt(i+3).putInt(i+4);
  Files.write(bank.toPath(),pcm.array());
  AudioTrack.bytes=0;
  CountDownLatch rawReady=new CountDownLatch(1);
  ArcadeBgm raw=new ArcadeBgm(bank,temp,"ten_a2",new ArcadeBgm.Listener(){
   public void ready(ArcadeBgm b){rawReady.countDown();}
   public void failed(ArcadeBgm b,Exception e){failure.set(e);rawReady.countDown();}
  });
  raw.start();
  try {
   check(rawReady.await(3,TimeUnit.SECONDS)&&failure.get()==null);
   raw.playback(true,.5f);
   await(()->AudioTrack.bytes==AudioTrack.written.length);
   for(int i=0;i<AudioTrack.written.length;i+=4)check(AudioTrack.written[i]==4+(i/4)%2);
   check(AudioTrack.rate==28000&&MediaCodec.starts==1);
   raw.fade(false,35);
   await(()->AudioTrack.releases==2);
  } finally {raw.close();}
  check(failure.get()==null && temp.list().length==1);
  System.out.println("AAC and original Ten PCM playback, continuous wrap, fade, pause/resume and cache cleanup passed");
 }
}
"""

with tempfile.TemporaryDirectory(prefix="cinder-bgm-pcm-") as directory:
    scratch = Path(directory)
    media = scratch / "android/media"
    media.mkdir(parents=True)
    files = [PLAYER]
    for name, source in STUBS.items():
        stub = media / (name + ".java")
        stub.write_text("package android.media;\n" + source)
        files.append(stub)
    harness = scratch / "ArcadeBgmPcmTest.java"
    harness.write_text(HARNESS)
    cache = scratch / "pcm"
    cache.mkdir()
    subprocess.run(["javac", "-d", str(scratch), *map(str, files), str(harness)], check=True)
    subprocess.run(["java", "-cp", str(scratch), "com.wmmt.port.ArcadeBgmPcmTest", str(cache)], check=True)

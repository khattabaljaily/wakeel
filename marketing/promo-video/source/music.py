import numpy as np, soundfile as sf, json
sr=44100; TL=json.load(open("timeline.json")); T=TL[-1]["end"]+0.5
n=int(T*sr); t=np.arange(n)/sr; mix=np.zeros((n,2))
bpm=100; beat=60/bpm; bar=beat*4
def note(f): return 440*2**((f-69)/12)
chords=[[57,60,64,69],[53,57,60,65],[48,55,60,64],[55,59,62,67]]  # Am F C G
rng=np.random.default_rng(1)
# pad
for i in range(int(T/bar/2)+1):
    c=chords[i%4]; s0=i*bar*2; L=bar*2+1.0
    a,b=int(s0*sr),min(n,int((s0+L)*sr)); 
    if a>=n: break
    tt=np.arange(b-a)/sr; env=np.minimum(1,tt/1.2)*np.minimum(1,(L-tt)/1.0)
    for k,m in enumerate(c):
        for det,pan in [(-0.08,0.3),(0.08,0.7)]:
            f=note(m-12 if k==0 else m)*(1+det/100)
            w=np.sin(2*np.pi*f*tt)+0.3*np.sin(2*np.pi*2*f*tt)+0.12*np.sin(2*np.pi*3*f*tt)
            mix[a:b,0]+=w*env*0.035*(1-pan); mix[a:b,1]+=w*env*0.035*pan
# arpeggio pluck from 'meet'
st=[s for s in TL if s["name"]=="meet"][0]["start"]; en=TL[-1]["start"]+2
k=0; x=st
while x<en:
    c=chords[int(x/(bar*2))%4]; m=c[[0,1,2,3,2,1,3,2][k%8]]+12
    a=int(x*sr); L=int(0.45*sr); tt=np.arange(min(L,n-a))/sr
    w=(np.sin(2*np.pi*note(m)*tt)+0.4*np.sin(2*np.pi*2*note(m)*tt))*np.exp(-tt*9)
    pan=0.5+0.3*np.sin(k); mix[a:a+len(tt),0]+=w*0.05*(1-pan); mix[a:a+len(tt),1]+=w*0.05*pan
    x+=beat/2; k+=1
# kick + hat from brand to cta
ks=[s for s in TL if s["name"]=="brand"][0]["start"]; ke=[s for s in TL if s["name"]=="cta"][0]["start"]+4
x=ks
while x<ke:
    a=int(x*sr); tt=np.arange(int(0.3*sr))/sr; f=50+90*np.exp(-tt*30)
    w=np.sin(2*np.pi*np.cumsum(f)/sr)*np.exp(-tt*12)*0.22; mix[a:a+len(w)]+=w[:,None][:n-a]
    h=int((x+beat/2)*sr); ht=np.arange(int(0.05*sr)); hw=rng.normal(0,1,len(ht))*np.exp(-ht/sr*80)*0.02
    hw=np.diff(hw,prepend=0); mix[h:h+len(hw)]+=hw[:,None][:max(0,n-h)]
    x+=beat
# whoosh at each scene change
for s in TL[1:]:
    c=s["start"]; L=0.9; a=int((c-L*0.6)*sr); tt=np.arange(int(L*sr))/sr
    nz=rng.normal(0,1,len(tt)); 
    # simple lowpass sweep via moving average of varying width
    env=np.sin(np.pi*tt/L)**2
    out=np.convolve(nz,np.ones(6)/6,'same')*env*0.09
    mix[a:a+len(out),0]+=out*(1-tt/L); mix[a:a+len(out),1]+=out*(tt/L)
# fade in/out
fade=np.minimum(1,t/2)*np.minimum(1,(T-t)/3); mix*=fade[:,None]
mix/=np.max(np.abs(mix))*1.25
sf.write("music.wav",mix,sr); print("music",T)

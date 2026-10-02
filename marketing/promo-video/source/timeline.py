import json
meta=json.load(open("vo/meta.json"))
tail={"hook":0.9,"problem":1.3,"meet":2.2,"brand":1.4,"plan":1.4,"design":2.4,"review":1.4,"publish":1.8,"team":1.4,"cta":2.2,"credit":3.4}
lead={"hook":1.0}
t=0; out=[]
for m in meta:
    l=lead.get(m["name"],0.5)
    out.append({"name":m["name"],"start":round(t,3),"vo":round(t+l,3),"vodur":m["dur"],"text":m["text"],"end":round(t+l+m["dur"]+tail[m["name"]],3)})
    t=out[-1]["end"]
json.dump(out,open("timeline.json","w"),indent=1)
open("timeline.js","w").write("window.TL="+json.dumps({s["name"]:s for s in out})+";window.TOTAL="+str(round(t,3))+";")
for s in out: print(s["name"],s["start"],s["end"])
print("TOTAL",t)

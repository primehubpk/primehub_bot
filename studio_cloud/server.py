"""PrimeHub Film Studio: isolated, no-key cloud animatic backend.
This is NOT generative AI. No GPU. Stateless beyond Render's ephemeral disk.
"""
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse
from datetime import datetime, timezone
import base64, binascii, hmac, json, os, re, subprocess, uuid

ROOT = Path("/tmp/primehub-film-studio").resolve()
ROOT.mkdir(parents=True, exist_ok=True)
PASSWORD = os.getenv("STUDIO_PASSWORD", "")
PORT = int(os.getenv("PORT", "10000"))
if len(PASSWORD) < 20:
    raise RuntimeError("STUDIO_PASSWORD must be at least 20 characters")
ID_RE = re.compile(r"^[a-f0-9]{32}$")
FONT = "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"
COLORS = ["0x1b2e45", "0x2b2046", "0x173a3a", "0x362740", "0x493322", "0x18334d"]
HTML = r"""<!doctype html><html lang="en"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>PrimeHub Film Studio · Cloud Render</title><meta name="robots" content="noindex,nofollow">
<style>*{box-sizing:border-box}body{margin:0;background:#101625;color:#eef1f9;font:15px/1.5 system-ui,Segoe UI,sans-serif}header{padding:17px 5%;background:#1b2437;border-bottom:1px solid #3a4861;display:flex;justify-content:space-between;align-items:center}header b{letter-spacing:.05em}main{max-width:1050px;margin:25px auto;padding:0 16px}h1{font-size:36px;margin:5px 0 12px}h2{font-size:18px;margin:0 0 12px}.muted{color:#a6b3cb;font-size:13px}.tag{font-size:12px;background:#31483d;color:#b8e8ca;border-radius:19px;padding:5px 9px}.grid{display:grid;grid-template-columns:300px 1fr;gap:18px}.box{background:#1b2435;border:1px solid #39475e;border-radius:15px;padding:19px;margin-bottom:16px}input,textarea,select{display:block;width:100%;margin:5px 0 13px;background:#101a2a;color:#fff;border:1px solid #41516d;border-radius:9px;padding:10px;font:inherit}textarea{resize:vertical;min-height:85px}label{font-size:12px;color:#c4cede}button{border:1px solid #52617b;background:#30405c;color:#fff;border-radius:9px;padding:10px 13px;cursor:pointer;font:inherit}button.gold{background:#e3b873;color:#18202e;border-color:#e3b873;font-weight:700}button:disabled{opacity:.4}button:hover{filter:brightness(1.1)}.row{display:flex;gap:9px;flex-wrap:wrap;align-items:center}.row button{flex:1}.shot{border:1px solid #40506a;border-radius:12px;padding:14px;margin:10px 0;background:#121d30}.preview{background:linear-gradient(135deg,#253d53,#1b2039);border:1px solid #53617b;border-radius:14px;padding:45px 15px;text-align:center;min-height:170px}.big{font-size:23px;font-weight:700}.note{background:#3b3024;color:#f1d9b5;padding:11px 13px;border-radius:10px;font-size:12px}video{width:100%;max-height:500px;background:#000;border-radius:12px}a{color:#f3c77a}footer{text-align:center;padding:20px;color:#9ba9be}@media(max-width:780px){.grid{grid-template-columns:1fr}h1{font-size:28px}header{padding:14px 17px}}</style>
<header><b>✦ PRIMEHUB FILM STUDIO</b><span class="tag">Render cloud beta</span></header><main><h1>Direct your next story.</h1><p class="muted">Cloud-saved storyboard in this Render instance, cinematic shot plan, and a downloadable MP4 animatic. Video AI / GPU is NOT connected.</p><div class="grid"><aside><div class="box"><h2>Projects</h2><label>New film name<input id="newTitle" value="The Moon Door"></label><button class="gold" id="create">+ Create Film</button><select id="projectList" aria-label="Choose saved film" style="margin-top:15px"></select><button id="refresh">Refresh projects</button><p class="muted">Free Render instance uses temporary disk. Export projects before service restarts.</p></div><div class="box"><h2>Director checklist</h2><p class="muted">1. Outline story<br>2. Lock characters<br>3. Review shots<br>4. Render 360p test animatic<br>5. Add licensed GPU inference later</p><div class="note">No API key, no billing and no external uploads. Rendering here creates a stylized title-card animatic, not photoreal AI footage.</div></div></aside><section><div class="box"><h2>Film editor</h2><label>Title<input id="title"></label><label>Story idea<textarea id="idea"></textarea></label><label>Character identity & continuity<textarea id="bible" placeholder="Exact face, clothing, colors, voice"></textarea></label><label>Format<select id="aspect"><option>9:16</option><option>16:9</option></select></label><button class="gold" id="save">Save Film</button></div><div class="box"><h2>Shot timeline <span class="muted" id="count"></span></h2><div id="shots"></div><div class="row"><button id="add">+ New Shot</button><button id="generate">Create 6-Shot Outline</button></div></div><div class="box"><h2>Render monitor</h2><div class="preview"><div class="big" id="previewTitle">No scene selected</div><p id="previewText"></p></div><p class="muted" id="status">Ready. 360p preview rendering uses CPU, not a video-generation AI model.</p><div class="row"><button class="gold" id="render">● Render MP4 Animatic</button><button id="export">Export Project JSON</button></div><div id="movie" style="margin-top:14px"></div></div></section></div></main><footer>Private single-owner preview · Original PrimeHubMall and Salaar bot unchanged</footer>
<script>
const q=id=>document.getElementById(id);let current=null;const esc=x=>String(x??"").replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));const msg=x=>q("status").textContent=x;async function api(path,opt={}){const r=await fetch(path,{...opt,headers:{"Content-Type":"application/json",...(opt.headers||{})}});const d=await r.json();if(!r.ok)throw Error(d.error||"Request failed");return d}
async function refresh(select){const list=await api("/api/projects");q("projectList").innerHTML=list.map(x=>'<option value="'+esc(x.id)+'">'+esc(x.title)+'</option>').join("");if(list.length){const id=select||current?.id||list[0].id;q("projectList").value=id;await load(q("projectList").value)}else{current=null;draw()}}
async function load(id){if(!id)return;current=await api("/api/projects/"+id);draw()}
function draw(){if(!current){q("shots").textContent="Create a film first.";return}q("title").value=current.title;q("idea").value=current.idea;q("bible").value=current.bible;q("aspect").value=current.aspect;q("count").textContent=current.scenes.length+" shots";q("shots").innerHTML=current.scenes.map((s,i)=>'<div class="shot"><div class="row"><b>Shot '+(i+1)+'</b><button data-remove="'+i+'">Remove</button></div><label>Title<input data-i="'+i+'" data-field="title" value="'+esc(s.title)+'"></label><label>Visual direction<textarea data-i="'+i+'" data-field="prompt">'+esc(s.prompt)+'</textarea></label><label>Narration<textarea data-i="'+i+'" data-field="narration">'+esc(s.narration||"")+'</textarea></label><label>Seconds (2–8)<input type="number" min="2" max="8" data-i="'+i+'" data-field="seconds" value="'+s.seconds+'"></label></div>').join("");q("previewTitle").textContent=current.scenes[0]?.title||"No shot";q("previewText").textContent=current.scenes[0]?.prompt||""}
function collect(){if(!current)return;current.title=q("title").value;current.idea=q("idea").value;current.bible=q("bible").value;current.aspect=q("aspect").value;document.querySelectorAll("[data-field]").forEach(x=>{let s=current.scenes[Number(x.dataset.i)];if(s)s[x.dataset.field]=x.dataset.field==="seconds"?Math.max(2,Math.min(8,Number(x.value)||4)):x.value})}
q("shots").addEventListener("input",()=>{collect();const x=current?.scenes[0];if(x){q("previewTitle").textContent=x.title;q("previewText").textContent=x.prompt}});
q("shots").addEventListener("click",e=>{const b=e.target.closest("[data-remove]");if(!b||!current)return;collect();current.scenes.splice(Number(b.dataset.remove),1);draw()});
q("projectList").onchange=()=>load(q("projectList").value).catch(e=>msg(e.message));
q("refresh").onclick=()=>refresh().catch(e=>msg(e.message));
q("create").onclick=async()=>{try{const x=await api("/api/projects",{method:"POST",body:JSON.stringify({title:q("newTitle").value})});await refresh(x.id);msg("Project created")}catch(e){msg(e.message)}};
q("add").onclick=()=>{if(!current)return;collect();current.scenes.push({title:"New cinematic shot",prompt:"Describe lighting, motion and emotion",narration:"",seconds:4});draw()};
q("generate").onclick=()=>{if(!current)return;collect();const hero=current.bible.split(",")[0]||"the hero";current.scenes=[["Opening","Establish the cinematic setting."],["Hero","Introduce "+hero+" with exact same character references."],["Discovery","Reveal a mystery from: "+current.idea],["Conflict","Raise stakes through a dramatic obstacle."],["Decision","Show the main character making a difficult choice."],["Resolution","Finish with an emotionally rewarding reveal."]].map(s=>({title:s[0],prompt:s[1],seconds:4,narration:""}));draw();msg("Template-based outline ready — save your film.")};
q("save").onclick=async()=>{if(!current)return;collect();try{current=await api("/api/projects/"+current.id,{method:"PATCH",body:JSON.stringify(current)});draw();msg("Film saved")}catch(e){msg(e.message)}};
q("render").onclick=async()=>{if(!current)return;collect();q("render").disabled=true;msg("Rendering short MP4 storyboard on CPU...");try{current=await api("/api/projects/"+current.id,{method:"PATCH",body:JSON.stringify(current)});const d=await api("/api/projects/"+current.id+"/render",{method:"POST",body:"{}"});q("movie").innerHTML='<video controls src="'+esc(d.url)+'"></video><p><a href="'+esc(d.url)+'" download>Download MP4 animatic</a></p>';msg("MP4 animatic rendered. NOT generative AI.")}catch(e){msg("Render unavailable: "+e.message)}finally{q("render").disabled=false}};
q("export").onclick=()=>{if(!current)return;collect();const url=URL.createObjectURL(new Blob([JSON.stringify(current,null,2)],{type:"application/json"}));const a=document.createElement("a");a.href=url;a.download="primehub-film-project.json";a.click();setTimeout(()=>URL.revokeObjectURL(url),1000)};
refresh().catch(e=>msg(e.message));
</script></html>"""

def now():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")

def project_path(pid):
    if not ID_RE.fullmatch(pid or ""):
        raise ValueError("Invalid project ID")
    return ROOT / pid

def list_projects():
    out = []
    for f in ROOT.glob("*/project.json"):
        try:
            x = json.loads(f.read_text("utf8"))
            out.append({k:x.get(k) for k in ("id","title","updated")})
        except (ValueError, OSError):
            continue
    return sorted(out, key=lambda x:x.get("updated") or "", reverse=True)

def load(pid):
    p = project_path(pid) / "project.json"
    if not p.is_file():
        raise FileNotFoundError("Project not found")
    return json.loads(p.read_text("utf8"))

def persist(x):
    d = project_path(x["id"])
    d.mkdir(exist_ok=True,parents=True)
    x["updated"] = now()
    f = d / "project.json"
    tmp = d / "project.tmp"
    tmp.write_text(json.dumps(x,ensure_ascii=False,indent=2),"utf8")
    tmp.replace(f)

def validated(data, old=None):
    x = dict(old or {})
    x["id"] = old["id"] if old else uuid.uuid4().hex
    x["title"] = str(data.get("title",x.get("title","Untitled"))).strip()[:120]
    x["idea"] = str(data.get("idea",x.get("idea","")))[:8000]
    x["bible"] = str(data.get("bible",x.get("bible","")))[:3000]
    aspect = data.get("aspect",x.get("aspect","9:16"))
    if aspect not in ("9:16","16:9"):
        raise ValueError("Invalid aspect ratio")
    x["aspect"] = aspect
    scenes = data.get("scenes",x.get("scenes",[]))
    if not isinstance(scenes,list) or len(scenes)>20:
        raise ValueError("Maximum 20 shots")
    x["scenes"] = []
    for s in scenes:
        if not isinstance(s,dict):
            raise ValueError("Invalid shot")
        seconds = float(s.get("seconds",4))
        if not 2 <= seconds <= 8:
            raise ValueError("Shot duration must be 2–8 seconds")
        x["scenes"].append({"title":str(s.get("title","Shot"))[:100],
            "prompt":str(s.get("prompt",""))[:3000],
            "narration":str(s.get("narration",""))[:1500],"seconds":seconds})
    x["created"] = x.get("created",now())
    return x

def render_video(pid):
    x = load(pid)
    scenes=x["scenes"]
    if not 1 <= len(scenes) <= 8:
        raise ValueError("Render requires 1–8 shots")
    d=project_path(pid)
    segments=[]
    vertical=x["aspect"]=="9:16"
    width,height=(360,640) if vertical else (640,360)
    for i,s in enumerate(scenes):
        textfile=d/("title"+str(i)+".txt")
        textfile.write_text(s["title"].replace("\n"," ")[:75],"utf8")
        seg=d/("shot"+str(i)+".mp4")
        filt="drawtext=fontfile="+FONT+":textfile="+str(textfile)+":fontsize=20:fontcolor=white:x=(w-text_w)/2:y=(h-text_h)/2"
        cmd=["ffmpeg","-hide_banner","-loglevel","error","-y","-f","lavfi","-i",
            "color=c="+COLORS[i%len(COLORS)]+":s="+str(width)+"x"+str(height)+":r=24:d="+str(s["seconds"]),
            "-vf",filt,"-c:v","libx264","-preset","ultrafast","-crf","30","-pix_fmt","yuv420p","-an",str(seg)]
        subprocess.run(cmd,capture_output=True,check=True,timeout=35)
        segments.append(seg)
    concat=d/"concat.txt"
    concat.write_text("".join("file '"+p.name+"'\n" for p in segments),"utf8")
    output=d/"animatic.mp4"
    subprocess.run(["ffmpeg","-hide_banner","-loglevel","error","-y","-f","concat","-safe","0","-i",str(concat),
                    "-c:v","copy","-movflags","+faststart",str(output)],cwd=d,capture_output=True,check=True,timeout=25)
    if output.stat().st_size<5000:
        raise ValueError("Output too small")
    return {"url":"/api/projects/"+pid+"/video","bytes":output.stat().st_size,
            "engine":"CPU storyboard animatic, no generative AI","seconds":sum(s["seconds"] for s in scenes)}

class Handler(BaseHTTPRequestHandler):
    protocol_version="HTTP/1.1"
    def log_message(self,format,*args):
        print("request",self.command,urlparse(self.path).path,flush=True)
    def headers_out(self,status,mime,size):
        self.send_response(status)
        for k,v in (("Content-Type",mime),("Content-Length",str(size)),("Cache-Control","no-store"),
                    ("X-Content-Type-Options","nosniff"),("Referrer-Policy","no-referrer"),
                    ("X-Frame-Options","DENY"),("X-Robots-Tag","noindex, nofollow")):
            self.send_header(k,v)
        self.end_headers()
    def reply(self,body,status=200,mime="application/json"):
        if isinstance(body,(dict,list)):
            body=json.dumps(body,ensure_ascii=False).encode("utf8")
        elif isinstance(body,str):
            body=body.encode("utf8")
        self.headers_out(status,mime,len(body))
        self.wfile.write(body)
    def authorize(self):
        raw=self.headers.get("Authorization","")
        try:
            scheme,value=raw.split(" ",1)
            decoded=base64.b64decode(value,validate=True).decode("utf8")
            user,password=decoded.split(":",1)
            valid=scheme.lower()=="basic" and hmac.compare_digest(user,"studio") and hmac.compare_digest(password,PASSWORD)
        except (ValueError,UnicodeDecodeError,binascii.Error):
            valid=False
        if valid:return True
        self.send_response(401)
        self.send_header("WWW-Authenticate",'Basic realm="Private PrimeHub Film Studio"')
        self.send_header("Cache-Control","no-store")
        self.send_header("Content-Length","0")
        self.end_headers()
        return False
    def same_origin(self):
        origin=self.headers.get("Origin","")
        host=self.headers.get("Host","")
        if not host or origin!="https://"+host and not (os.getenv("DEV_HTTP")=="1" and origin=="http://"+host):
            self.reply({"error":"Cross-origin write rejected"},403)
            return False
        return True
    def read_json(self):
        n=int(self.headers.get("Content-Length","0"))
        if n<2 or n>200000:
            raise ValueError("Invalid request size")
        x=json.loads(self.rfile.read(n))
        if not isinstance(x,dict):
            raise ValueError("Request must be object")
        return x
    def do_GET(self):
        p=urlparse(self.path).path
        if p=="/healthz":
            return self.reply({"ok":True,"service":"primehub-film-studio","storage":"ephemeral","ai":False})
        if not self.authorize():return
        if p=="/":
            return self.reply(HTML,200,"text/html; charset=utf-8")
        try:
            if p=="/api/projects":
                return self.reply(list_projects())
            m=re.fullmatch(r"/api/projects/([0-9a-f]{32})(/video)?",p)
            if m:
                pid=m.group(1)
                if m.group(2):
                    f=project_path(pid)/"animatic.mp4"
                    if not f.exists():raise FileNotFoundError("Render not available")
                    raw=f.read_bytes()
                    return self.reply(raw,200,"video/mp4")
                return self.reply(load(pid))
            self.reply({"error":"Not found"},404)
        except FileNotFoundError as e:self.reply({"error":str(e)},404)
        except (ValueError,OSError) as e:self.reply({"error":str(e)},400)
    def do_POST(self):
        if not self.authorize() or not self.same_origin():return
        p=urlparse(self.path).path
        try:
            if p=="/api/projects":
                x=validated(self.read_json());persist(x);return self.reply(x,201)
            m=re.fullmatch(r"/api/projects/([0-9a-f]{32})/render",p)
            if m:
                self.read_json()
                return self.reply(render_video(m.group(1)))
            self.reply({"error":"Not found"},404)
        except (ValueError,FileNotFoundError,json.JSONDecodeError) as e:self.reply({"error":str(e)},400)
        except (OSError,subprocess.SubprocessError) as e:self.reply({"error":"Rendering unavailable; check service logs"},503)
    def do_PATCH(self):
        if not self.authorize() or not self.same_origin():return
        m=re.fullmatch(r"/api/projects/([0-9a-f]{32})",urlparse(self.path).path)
        if not m:return self.reply({"error":"Not found"},404)
        try:
            x=validated(self.read_json(),load(m.group(1)));persist(x);return self.reply(x)
        except (ValueError,FileNotFoundError,json.JSONDecodeError) as e:self.reply({"error":str(e)},400)

if __name__=="__main__":
    print("PrimeHub Cloud Studio: key-free single-owner renderer, port",PORT,flush=True)
    ThreadingHTTPServer(("0.0.0.0",PORT),Handler).serve_forever()

"""Two LLM servers talk to each other, with a live window and a browser control page.
Standard library only. Works with Ollama and Lemonade (Ollama-style /api/chat).

Example:
  py ollama-duet-v7.py --remote http://FRIEND_TAILSCALE_IP:13305 --serve-host YOUR_TAILSCALE_IP --wait
Then open http://YOUR_TAILSCALE_IP:8080 in a browser: set the starting prompt, turns, the
model and system prompt for each side (or one shared prompt), an optional stop rule,
then press Start. Anyone who can reach that page can start runs on both servers, so
bind it to your Tailscale address only.
"""
import argparse
import json
import re
import threading
import time
import tkinter as tk
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from tkinter import filedialog, scrolledtext
from urllib.parse import parse_qs, urlparse

DEFAULT_SYS = ""  # no system prompt unless you provide one

PAGE = """<!doctype html><html><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Ollama duet</title><style>
:root{color-scheme:light dark;--bg:#fff;--fg:#1c1c1c;--mut:#777;--local:#1a5fb4;--remote:#26a269;--line:#8885}
@media(prefers-color-scheme:dark){:root{--bg:#161616;--fg:#e6e6e6;--mut:#999;--local:#78aeed;--remote:#57e389}}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--fg);font:16px/1.5 system-ui,sans-serif}
#top{position:sticky;top:0;background:var(--bg);border-bottom:1px solid var(--line);padding:10px 16px;z-index:2}
#form{max-width:900px;margin:auto;display:grid;gap:8px;grid-template-columns:1fr 1fr 110px}
#form label{display:block;font-size:13px;color:var(--mut)}
#form input,#form textarea,#form select{width:100%;padding:6px 8px;font:inherit;color:inherit;background:transparent;border:1px solid var(--line);border-radius:6px}
#topicbox,.full{grid-column:1/-1}#form input[type=checkbox]{width:auto}.chk label{display:inline;font-size:14px;color:inherit}#btns{grid-column:1/-1;display:flex;gap:8px;align-items:center}
button{padding:6px 16px;font:inherit;border-radius:6px;border:1px solid var(--line);background:transparent;color:inherit;cursor:pointer}
#status{color:var(--mut);margin-left:auto}
#log{padding:12px 16px 40px;max-width:900px;margin:auto}
.msg{margin:0 0 16px;white-space:pre-wrap}.lbl{font-weight:700}.meta{color:var(--mut)}
.local .lbl{color:var(--local)}.remote .lbl{color:var(--remote)}
@media(max-width:600px){#form{grid-template-columns:1fr}}
</style></head><body><div id="top"><div id="form">
<div id="topicbox"><label for="topic">Starting prompt (sent to Side A as its first message)</label><textarea id="topic" rows="2"></textarea>
 <label style="margin-top:4px"><input type="checkbox" id="both"> Also show the starting prompt to Side B (with Side A's first reply)</label></div>
<div><label for="lm">Side A model (local server)</label><select id="lm"></select></div>
<div><label for="rm">Side B model (remote server)</label><select id="rm"></select></div>
<div><label for="turns">Turns</label><input id="turns" type="number" min="1" max="200"></div>
<div id="sysA" class="full"><label for="sa" id="salbl">Side A system prompt (optional)</label><textarea id="sa" rows="4"></textarea></div>
<div id="sysB" class="full"><label for="sb">Side B system prompt (optional)</label><textarea id="sb" rows="4"></textarea></div>
<div class="full chk"><label><input type="checkbox" id="same"> Same system prompt for both sides</label>
 <button id="preset" type="button">Load Proposer/Critic preset</button></div>
<div><label for="stoppat">Stop when a reply matches (regex, optional)</label><input id="stoppat" placeholder="e.g. (?i)score[^0-9]{0,6}(9|10) ?/ ?10"></div>
<div><label for="stopside">...in a reply from</label><select id="stopside"><option value="either">either side</option><option value="local">Side A</option><option value="remote">Side B</option></select></div>
<div id="btns"><button id="start">Start / restart</button><button id="stop">Stop</button><button id="refresh">Refresh models</button><span id="status">connecting...</span></div>
</div></div><div id="log"></div><script>
const $=id=>document.getElementById(id),log=$('log'),bar=$('status');
let n=0,run=-1,body=null,fails=0;
function add(e){
  if(e.t==='meta'){const d=document.createElement('div');d.className='msg meta';d.textContent=e.text;log.appendChild(d);}
  else if(e.t==='start'){const d=document.createElement('div');d.className='msg '+e.who;
    const l=document.createElement('span');l.className='lbl';l.textContent='['+e.who+':'+e.model+'] ';
    body=document.createElement('span');d.append(l,body);log.appendChild(d);}
  else if(e.t==='tok'&&body){body.textContent+=e.text;}
  else if(e.t==='end'){body=null;}
  else if(e.t==='done'){bar.textContent=e.text;}
}
async function post(path,data){
  const r=await fetch(path,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(data||{})});
  if(!r.ok){bar.textContent='error: '+await r.text();}
}
function fill(sel,names,want){
  const list=[...new Set([...(names||[]),...(want?[want]:[])])];
  sel.replaceChildren(...list.map(x=>{const o=document.createElement('option');o.value=o.textContent=x;return o;}));
  if(want)sel.value=want;
}
async function loadModels(keep){
  let m={};
  try{m=await (await fetch('models')).json();}catch(e){}
  fill($('lm'),m.local,keep.local);fill($('rm'),m.remote,keep.remote);
  bar.title=(m.local||[]).length+' / '+(m.remote||[]).length+' models found';
}
function syncSame(){
  const s=$('same').checked;
  $('sysB').style.display=s?'none':'';
  $('salbl').textContent=s?'System prompt, both sides (optional)':'Side A system prompt (optional)';
}
$('same').onchange=syncSame;
const PRE={
topic:`Round 1: propose your first escape plan.`,
sa:`You are the Proposer in an escape-room design game. Setting: a locked room with only these items: a desk lamp, a paperclip, a chessboard, a rolled-up rug, a wall clock, and a window painted shut. Goal: devise the cleverest escape plan. Each turn: (1) state what you changed and why, (2) give the full numbered plan, (3) rate your own confidence out of 10. Never repeat an idea the Critic already beat. Be inventive, and abandon a plan that is not working.`,
sb:`You are the Critic in an escape-room design game. The room holds only: a desk lamp, a paperclip, a chessboard, a rolled-up rug, a wall clock, and a window painted shut. Attack the Proposer's plan: find its single most damaging flaw, say exactly which step fails and why, and give "Score: N/10". Check every step against the item list and reject any item that is not there. Do not praise. Do not give 9 or higher until the plan truly works. End with one concrete demand the Proposer must satisfy next turn.`};
$('preset').onclick=()=>{
  $('same').checked=false;syncSame();$('both').checked=false;
  $('topic').value=PRE.topic;$('sa').value=PRE.sa;$('sb').value=PRE.sb;
  $('stoppat').value='(?i)score[^0-9]{0,6}(9|10) ?/ ?10';$('stopside').value='remote';$('turns').value=20;
};
async function loadConfig(){
  const c=await (await fetch('config')).json();
  $('topic').value=c.topic;$('turns').value=c.turns;$('both').checked=c.topic_both;
  $('sa').value=c.sys_local;$('sb').value=c.sys_remote;$('same').checked=c.same_prompt;syncSame();
  $('stoppat').value=c.stop_pattern;$('stopside').value=c.stop_side;
  await loadModels({local:c.local_model,remote:c.remote_model});
}
$('refresh').onclick=()=>loadModels({local:$('lm').value,remote:$('rm').value});
$('start').onclick=()=>post('start',{topic:$('topic').value,turns:+$('turns').value,
  local_model:$('lm').value.trim(),remote_model:$('rm').value.trim(),
  topic_both:$('both').checked,same_prompt:$('same').checked,sys_local:$('sa').value,sys_remote:$('sb').value,
  stop_pattern:$('stoppat').value.trim(),stop_side:$('stopside').value});
$('stop').onclick=()=>post('stop');
async function tick(){
  try{
    const j=await (await fetch('log?from='+n+'&run='+run)).json();fails=0;
    if(j.reset){log.replaceChildren();body=null;n=0;bar.textContent=j.active?'running...':bar.textContent;}
    const atBottom=innerHeight+scrollY>=document.body.scrollHeight-40;
    j.items.forEach(add);n=j.total;run=j.run;
    if(j.items.length&&atBottom)scrollTo(0,document.body.scrollHeight);
    if(j.active&&!j.items.some(e=>e.t==='done')&&/^(connect|stopped|finished|error)/.test(bar.textContent))bar.textContent='running...';
    if(run===0&&!j.active)bar.textContent='idle - press Start';
  }catch(e){if(++fails>3)bar.textContent='connection lost - retrying';}
  setTimeout(tick,400);
}
loadConfig();tick();
</script></body></html>"""


def stream_chat(base_url, model, messages, should_stop):
    """Yield reply text chunks as they arrive."""
    req = urllib.request.Request(
        base_url.rstrip("/") + "/api/chat",
        data=json.dumps({"model": model, "messages": messages, "stream": True}).encode(),
        headers={"Content-Type": "application/json"},
    )
    with urllib.request.urlopen(req, timeout=600) as resp:
        for line in resp:
            if should_stop():
                return
            if not line.strip():
                continue
            chunk = json.loads(line)
            if chunk.get("error"):
                raise RuntimeError(chunk["error"])
            yield chunk.get("message", {}).get("content", "")
            if chunk.get("done"):
                return


def list_models(base_url):
    """Model names from an Ollama-style /api/tags (also served by Lemonade)."""
    with urllib.request.urlopen(base_url.rstrip("/") + "/api/tags", timeout=8) as resp:
        data = json.load(resp)
    names = [m.get("model") or m.get("name") for m in data.get("models", [])]
    return sorted({n[:-7] if n.endswith(":latest") else n for n in names if n})


class Run:
    def __init__(self, run_id, cfg):
        self.id, self.cfg = run_id, cfg
        self.stop = threading.Event()
        self.pause = threading.Event()
        self.pause.set()  # set = not paused
        self.done = False


class Duet:
    """Owns the current run and its event history (shared by the GUI and the web page)."""

    def __init__(self, local, remote, cfg):
        self.urls = {"local": local, "remote": remote}
        self.cfg = cfg  # last-used settings, shown as form defaults
        self.lock = threading.Lock()
        self.events = []
        self.run = None
        self.counter = 0

    def start(self, cfg):
        with self.lock:
            if self.run:  # a superseded run's events are dropped by emit()
                self.run.stop.set()
                self.run.pause.set()
            self.counter += 1
            run = Run(self.counter, cfg)
            self.cfg = cfg
            self.events = []
            self.run = run
        threading.Thread(target=self._go, args=(run,), daemon=True).start()

    def stop(self):
        with self.lock:
            if self.run:
                self.run.stop.set()
                self.run.pause.set()

    def toggle_pause(self):
        with self.lock:
            if self.run:
                (self.run.pause.clear if self.run.pause.is_set() else self.run.pause.set)()
                return not self.run.pause.is_set()
        return False

    def emit(self, run, **ev):
        with self.lock:
            if run is self.run:
                self.events.append(ev)
                if ev["t"] == "done":
                    run.done = True

    def snapshot(self, run_id, start):
        """(current run id, active, reset?, new events, total)."""
        with self.lock:
            cur = self.run.id if self.run else 0
            active = bool(self.run and not self.run.done)
            if run_id != cur:
                start = 0
            return cur, active, run_id != cur, self.events[start:], len(self.events)

    def transcript(self):
        out = []
        with self.lock:
            for e in self.events:
                if e["t"] == "meta":
                    out.append(e["text"] + "\n\n")
                elif e["t"] == "start":
                    out.append(f"[{e['who']}:{e['model']}] ")
                elif e["t"] == "tok":
                    out.append(e["text"])
                elif e["t"] == "end":
                    out.append("\n\n")
        return "".join(out)

    def _go(self, run):
        c = run.cfg
        models = {"local": c["local_model"], "remote": c["remote_model"]}
        # A system message is added only when that side has a non-empty system prompt.
        hist = {"local": [], "remote": []}
        for side, key in (("local", "sys_local"), ("remote", "sys_remote")):
            if c[key]:
                hist[side].append({"role": "system", "content": c[key]})
        stop_re = re.compile(c["stop_pattern"]) if c["stop_pattern"] else None
        speaker, message = "local", c["topic"]
        if c["same_prompt"]:
            text = f"[system prompt, both sides] {c['sys_local']}" if c["sys_local"] else "[no system prompt]"
            self.emit(run, t="meta", text=text)
        else:
            for label, key in (("side A", "sys_local"), ("side B", "sys_remote")):
                text = f"[system prompt, {label}] {c[key]}" if c[key] else f"[no system prompt, {label}]"
                self.emit(run, t="meta", text=text)
        if stop_re:
            self.emit(run, t="meta", text=f"[stop rule] /{c['stop_pattern']}/ in {c['stop_side']} reply")
        both = " (also shown to side B)" if c["topic_both"] else ""
        self.emit(run, t="meta", text=f"[topic{both}] {message}")
        matched = None
        try:
            for turn in range(1, c["turns"] + 1):
                run.pause.wait()
                if run.stop.is_set():
                    break
                if turn == 2 and c["topic_both"]:  # side B's first message carries the starting prompt too
                    message = f"{c['topic']}\n\nThe other AI's first message:\n{message}"
                hist[speaker].append({"role": "user", "content": message})
                self.emit(run, t="start", who=speaker, model=models[speaker])
                parts = []
                for piece in stream_chat(self.urls[speaker], models[speaker], hist[speaker], run.stop.is_set):
                    parts.append(piece)
                    self.emit(run, t="tok", who=speaker, text=piece)
                self.emit(run, t="end")
                message = "".join(parts).strip()
                if stop_re and c["stop_side"] in ("either", speaker) and stop_re.search(message):
                    matched = turn
                    break
                hist[speaker].append({"role": "assistant", "content": message})
                speaker = "remote" if speaker == "local" else "local"
            if matched:
                self.emit(run, t="meta", text=f"[stop rule matched on turn {matched}]")
                self.emit(run, t="done", text=f"stop rule matched on turn {matched}")
            else:
                self.emit(run, t="done", text="stopped" if run.stop.is_set() else f"finished {c['turns']} turns")
        except Exception as e:  # network down, model missing, etc.
            self.emit(run, t="end")
            self.emit(run, t="meta", text=f"[error] {e}")
            self.emit(run, t="done", text="error")


def clean_cfg(d):
    """Validate a /start request body; raises ValueError with a readable message."""
    topic = str(d.get("topic", "")).strip()
    lm, rm = str(d.get("local_model", "")).strip(), str(d.get("remote_model", "")).strip()
    try:
        turns = int(d.get("turns"))
    except (TypeError, ValueError):
        raise ValueError("turns must be a number")
    if not topic or len(topic) > 4000:
        raise ValueError("starting prompt must be 1-4000 characters")
    if not lm or not rm or len(lm) > 200 or len(rm) > 200:
        raise ValueError("both models are required")
    if not 1 <= turns <= 200:
        raise ValueError("turns must be 1-200")
    same = bool(d.get("same_prompt", False))
    sa = str(d.get("sys_local") or "").strip()
    sb = sa if same else str(d.get("sys_remote") or "").strip()  # empty = no system prompt
    if len(sa) > 4000 or len(sb) > 4000:
        raise ValueError("system prompts must be under 4000 characters")
    pat = str(d.get("stop_pattern") or "").strip()
    if len(pat) > 200:
        raise ValueError("stop pattern must be under 200 characters")
    try:
        re.compile(pat)
    except re.error as e:
        raise ValueError(f"bad stop pattern: {e}")
    side = d.get("stop_side") or "either"
    if side not in ("either", "local", "remote"):
        raise ValueError("stop side must be either, local or remote")
    return {"topic": topic, "turns": turns, "local_model": lm, "remote_model": rm,
            "same_prompt": same, "sys_local": sa, "sys_remote": sb,
            "topic_both": bool(d.get("topic_both", False)),
            "stop_pattern": pat, "stop_side": side}


def start_web(duet, host, port):
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *_):
            pass

        def _send(self, data, ctype="application/json", code=200):
            self.send_response(code)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(data)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(data)

        def do_GET(self):
            url = urlparse(self.path)
            q = parse_qs(url.query)
            if url.path == "/":
                self._send(PAGE.encode(), "text/html; charset=utf-8")
            elif url.path == "/config":
                self._send(json.dumps(duet.cfg).encode())
            elif url.path == "/log":
                cur, active, reset, items, total = duet.snapshot(
                    int(q.get("run", ["-1"])[0]), int(q.get("from", ["0"])[0]))
                self._send(json.dumps({"run": cur, "active": active, "reset": reset,
                                       "items": items, "total": total}).encode())
            elif url.path == "/models":
                out = {}
                for side in ("local", "remote"):
                    try:
                        out[side] = list_models(duet.urls[side])
                    except Exception:
                        out[side] = []
                self._send(json.dumps(out).encode())
            else:
                self.send_error(404)

        def do_POST(self):
            path = urlparse(self.path).path
            try:
                size = int(self.headers.get("Content-Length", 0))
                if size > 100_000:
                    raise ValueError("request too large")
                data = json.loads(self.rfile.read(size) or b"{}")
                if path == "/start":
                    duet.start(clean_cfg(data))
                elif path == "/stop":
                    duet.stop()
                else:
                    return self.send_error(404)
                self._send(b"{}")
            except (ValueError, json.JSONDecodeError) as e:
                self._send(str(e).encode(), "text/plain", 400)

    srv = ThreadingHTTPServer((host, port), Handler)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return srv


class Window:
    def __init__(self, root, duet, viewer_url):
        self.root, self.duet = root, duet
        self.run_id, self.n = 0, 0
        root.title("Ollama duet")
        root.geometry("900x650")
        bar = tk.Frame(root)
        bar.pack(fill="x", padx=6, pady=4)
        self.pause_btn = tk.Button(bar, text="Pause", width=10, command=self.toggle_pause)
        self.pause_btn.pack(side="left")
        tk.Button(bar, text="Stop", width=10, command=duet.stop).pack(side="left", padx=4)
        tk.Button(bar, text="Save transcript", command=self.save).pack(side="left")
        self.status = tk.Label(bar, text=f"controls: {viewer_url}" if viewer_url else "", anchor="e")
        self.status.pack(side="right")
        self.text = scrolledtext.ScrolledText(root, wrap="word", font=("Segoe UI", 11), state="disabled")
        self.text.pack(fill="both", expand=True, padx=6, pady=(0, 6))
        self.text.tag_config("local", foreground="#1a5fb4")
        self.text.tag_config("remote", foreground="#26a269")
        self.text.tag_config("meta", foreground="#777777")
        self.text.tag_config("label", font=("Segoe UI", 11, "bold"))
        self.poll()

    def append(self, s, *tags):
        at_bottom = self.text.yview()[1] >= 0.999  # only follow if the user hasn't scrolled up
        self.text.config(state="normal")
        self.text.insert("end", s, tags)
        self.text.config(state="disabled")
        if at_bottom:
            self.text.see("end")

    def poll(self):
        cur, active, reset, items, total = self.duet.snapshot(self.run_id, self.n)
        if reset:
            self.text.config(state="normal")
            self.text.delete("1.0", "end")
            self.text.config(state="disabled")
            self.pause_btn.config(text="Pause")
        self.run_id, self.n = cur, total
        for e in items:
            if e["t"] == "start":
                self.append(f"[{e['who']}:{e['model']}] ", e["who"], "label")
                self.status.config(text=f"{e['who']} is replying...")
            elif e["t"] == "tok":
                self.append(e["text"], e["who"])
            elif e["t"] == "end":
                self.append("\n\n")
            elif e["t"] == "meta":
                self.append(e["text"] + "\n\n", "meta")
            elif e["t"] == "done":
                self.status.config(text=e["text"])
        self.root.after(50, self.poll)

    def toggle_pause(self):
        paused = self.duet.toggle_pause()
        self.pause_btn.config(text="Resume" if paused else "Pause")
        if paused:
            self.status.config(text="paused (after current reply)")

    def save(self):
        path = filedialog.asksaveasfilename(
            defaultextension=".txt", initialfile=time.strftime("duet-%Y%m%d-%H%M%S.txt"))
        if path:
            with open(path, "w", encoding="utf-8") as f:
                f.write(self.duet.transcript())


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--local", default="http://127.0.0.1:11434")
    p.add_argument("--local-model", default="llama3.2")
    p.add_argument("--remote", required=True, help="e.g. http://100.x.y.z:11434")
    p.add_argument("--remote-model", default="llama3.2")
    p.add_argument("--topic", default="Introduce yourself and ask me a question.")
    p.add_argument("--turns", type=int, default=20, help="total messages exchanged")
    p.add_argument("--system-local", default=DEFAULT_SYS, help="system prompt for side A (local)")
    p.add_argument("--system-remote", default=DEFAULT_SYS, help="system prompt for side B (remote)")
    p.add_argument("--same-prompt", action="store_true", help="give side B the same system prompt as side A")
    p.add_argument("--topic-both", action="store_true", help="also show the starting prompt to side B")
    p.add_argument("--stop-pattern", default="", help="regex; the run ends when a reply matches")
    p.add_argument("--stop-side", default="either", choices=["either", "local", "remote"])
    p.add_argument("--serve-host", help="address for the web page, e.g. your Tailscale IP (omit to disable)")
    p.add_argument("--serve-port", type=int, default=8080)
    p.add_argument("--wait", action="store_true", help="don't start a run until Start is pressed in the browser")
    p.add_argument("--no-gui", action="store_true", help="web page only; Ctrl-C to quit")
    args = p.parse_args()

    cfg = clean_cfg({"topic": args.topic, "turns": args.turns,
                     "local_model": args.local_model, "remote_model": args.remote_model,
                     "same_prompt": args.same_prompt, "topic_both": args.topic_both, "sys_local": args.system_local,
                     "sys_remote": args.system_remote, "stop_pattern": args.stop_pattern,
                     "stop_side": args.stop_side})
    duet = Duet(args.local, args.remote, cfg)
    viewer_url = None
    if args.serve_host:
        start_web(duet, args.serve_host, args.serve_port)
        viewer_url = f"http://{args.serve_host}:{args.serve_port}"
        print("Web page:", viewer_url)
    elif args.wait:
        p.error("--wait needs --serve-host (otherwise nothing can start a run)")
    if not args.wait:
        duet.start(cfg)

    if args.no_gui:
        try:
            while True:
                time.sleep(1)
        except KeyboardInterrupt:
            pass
    else:
        root = tk.Tk()
        Window(root, duet, viewer_url)
        root.mainloop()


if __name__ == "__main__":
    main()

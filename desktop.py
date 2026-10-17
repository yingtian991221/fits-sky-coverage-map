"""Windows desktop launcher and supervised local service (also usable from Python)."""
import argparse
import json
import os
from pathlib import Path
import subprocess
import sys
import urllib.request
import webbrowser

def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--home',default=str(Path(sys.executable if getattr(sys,'frozen',False) else __file__).resolve().parent))
    parser.add_argument('--port',type=int,default=8765)
    parser.add_argument('--serve',action='store_true')
    args=parser.parse_args()
    base=Path(args.home).resolve();base.mkdir(parents=True,exist_ok=True)
    for name in ('data','tmp'):(base/name).mkdir(exist_ok=True)
    os.environ.update(FITS_SKY_HOME=str(base),TEMP=str(base/'tmp'),TMP=str(base/'tmp'))
    if args.serve:
        import app
        from waitress import serve
        app.ar.connect().close()
        serve(app.app,host='127.0.0.1',port=args.port,threads=8)
        return
    import tkinter as tk
    root=tk.Tk();root.title('FITS Sky Coverage Map / 天空覆盖地图');root.geometry('570x245')
    message=tk.StringVar(value='正在启动本机服务…')
    tk.Label(root,text='FITS Sky Coverage Map',font=('Segoe UI',17)).pack(pady=12)
    tk.Label(root,textvariable=message,wraplength=540).pack(pady=5)
    tk.Label(root,text='关闭此窗口会停止由它启动的服务；索引和缓存仍保留。',wraplength=540).pack()
    url=f'http://127.0.0.1:{args.port}'
    process=None; log=None; retries=0;opened=False;closing=False;starting=False
    def health():
        try:
            with urllib.request.urlopen(url+'/api/health',timeout=.5) as r:value=json.load(r)
            return value.get('application')=='fits-sky-coverage-map' and Path(value.get('home','')).resolve()==base
        except Exception:return False
    def start():
        nonlocal process,log,starting
        command=[sys.executable] if getattr(sys,'frozen',False) else [sys.executable,str(Path(__file__).resolve())]
        command+=['--serve','--home',str(base),'--port',str(args.port)]
        log=open(base/'data'/'desktop-server.log','a',encoding='utf8')
        process=subprocess.Popen(command,cwd=base,stdout=log,stderr=log,creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
        starting=True
    def open_map():webbrowser.open(url)
    def stop_owned():
        nonlocal process,log
        if process and process.poll() is None:
            process.terminate()
            try:process.wait(timeout=5)
            except subprocess.TimeoutExpired:process.kill()
        process=None
        if log:log.close();log=None
    def restart():
        nonlocal retries
        if process:stop_owned();retries=0;start()
        else:message.set('已有其他启动器运行此服务；请在原启动器中管理。')
    def close():
        nonlocal closing
        closing=True;stop_owned();root.destroy()
    def poll():
        nonlocal retries,opened,starting
        if closing:return
        if process and process.poll() is not None:
            code=process.returncode;stop_owned()
            if retries<3:
                retries+=1;message.set(f'服务退出（{code}），正在重启 {retries}/3…');start()
            else:message.set('启动失败。请查看 data/desktop-server.log；端口可能已被占用。')
        elif health():
            starting=False;message.set(f'服务运行中 · {url}\n数据与缓存：{base / "data"}')
            if not opened:opened=True;open_map()
        root.after(2000,poll)
    buttons=tk.Frame(root);buttons.pack(pady=15)
    for title,callback in [('打开地图',open_map),('重启服务',restart),('退出',close)]:tk.Button(buttons,text=title,command=callback,width=14).pack(side='left',padx=5)
    root.protocol('WM_DELETE_WINDOW',close)
    if not health():start()
    root.after(100,poll);root.mainloop()

if __name__=='__main__':main()

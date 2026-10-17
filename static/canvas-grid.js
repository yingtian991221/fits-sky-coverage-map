// Coordinate lines projected with the atlas API; skip invalid/off-screen segments.
function drawCoordinateGrid(atlas) {
    let canvas=document.querySelector('#safeGrid');
    if(!canvas){canvas=document.createElement('canvas');canvas.id='safeGrid';canvas.style.cssText='position:absolute;inset:0;pointer-events:none;z-index:3';document.querySelector('#sky').append(canvas)}
    const box=document.querySelector('#aladin'),w=box.clientWidth,h=box.clientHeight;
    canvas.width=w;canvas.height=h;canvas.style.visibility='visible';
    const ctx=canvas.getContext('2d'),center=atlas.getRaDec(),fov=atlas.getFov()[0];
    ctx.strokeStyle='#934b8c88';ctx.fillStyle='#c781be';ctx.font='11px sans-serif';ctx.lineWidth=1;
    const steps=[.01,.02,.05,.1,.2,.5,1,2,5,10,15,30,60];
    const decStep=steps.find(x=>x>=fov/7)||60;
    const raSpan=Math.min(180,fov/Math.max(.08,Math.cos(center[1]*Math.PI/180)));
    const raStep=steps.find(x=>x>=raSpan/7)||60;
    const d0=Math.max(-89.99,center[1]-fov),d1=Math.min(89.99,center[1]+fov);
    const r0=center[0]-raSpan,r1=center[0]+raSpan;
    function line(points,label){
        let previous=null,labelPixel=null;ctx.beginPath();
        for(const point of points){
            const p=atlas.world2pix((point[0]%360+360)%360,point[1]);
            if(!p||!p.every(Number.isFinite)||p[0]<-w||p[0]>2*w||p[1]<-h||p[1]>2*h){previous=null;continue}
            if(previous&&Math.hypot(p[0]-previous[0],p[1]-previous[1])<Math.max(w,h)/3)ctx.lineTo(...p);else ctx.moveTo(...p);
            if(!labelPixel&&p[0]>45&&p[0]<w-55&&p[1]>45&&p[1]<h-45)labelPixel=p;
            previous=p;
        }
        ctx.stroke();if(labelPixel)ctx.fillText(label,labelPixel[0]+3,labelPixel[1]-3);
    }
    for(let ra=Math.ceil(r0/raStep)*raStep;ra<=r1;ra+=raStep)line(Array.from({length:81},(_,i)=>[ra,d0+(d1-d0)*i/80]),((ra%360+360)%360).toFixed(raStep<1?2:0)+'° RA');
    for(let dec=Math.ceil(d0/decStep)*decStep;dec<=d1;dec+=decStep)line(Array.from({length:81},(_,i)=>[r0+(r1-r0)*i/80,dec]),dec.toFixed(decStep<1?2:0)+'° Dec');
}

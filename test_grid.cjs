const vm=require('node:vm'),fs=require('node:fs'),assert=require('node:assert/strict');
const source=fs.readFileSync('static/canvas-grid.js','utf8');
let points=[],labels=0,projected=0;
const context={beginPath(){},stroke(){},moveTo(...p){points.push(p)},lineTo(...p){points.push(p)},fillText(){labels++}};
const canvas={style:{},getContext(){return context}},box={clientWidth:800,clientHeight:600};
const sandbox={document:{querySelector(id){return id==='#safeGrid'?canvas:box}}};
vm.createContext(sandbox);vm.runInContext(source,sandbox);
for(const [center,fov] of [[[359.9,0],5],[[0,89],20],[[180,-89],180]]){
    points=[];labels=0;projected=0;
    sandbox.drawCoordinateGrid({getRaDec:()=>center,getFov:()=>[fov],world2pix(ra,dec){
        assert(ra>=0&&ra<360);assert(dec>-90&&dec<90);projected++;
        if(projected%3===0)return null;
        if(projected%3===1)return [NaN,Infinity];
        return [ra*2,dec+300];
    }});
    assert(projected>0);assert(points.length>0);assert(points.every(p=>p.every(Number.isFinite)));
}
sandbox.drawCoordinateGrid({getRaDec:()=>[0,0],getFov:()=>[180],world2pix:()=>null});
console.log('Canvas grid: RA wrap, poles, invalid projection and fully hidden lines passed');

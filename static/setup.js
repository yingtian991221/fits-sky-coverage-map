// First-run guidance and installation settings, independent of survey availability.
const setupPanel=document.createElement('dialog');
setupPanel.id='setupPanel';
setupPanel.innerHTML=`<form id="settingsForm"><h2>Settings / 本机设置</h2>
<p>Settings are local to this installation. 配置仅保存在本机。</p>
<h3>ASTAP plate solver / 星场解析</h3>
<p>Optional for indexing and valid FITS WCS. 仅索引或读取有效 WCS 时无需安装。</p>
<label>Executable / 程序路径<input id="solverExecutable" placeholder="Auto-detect / 自动查找"></label>
<label>Star catalogue directory / 星表目录<input id="solverCatalog" placeholder="ASTAP default / ASTAP 默认目录"></label>
<label>Database abbreviation / 星表代号<input id="solverDatabase" placeholder="Auto / 自动，例如 d50"></label>
<label>Timeout per frame (seconds) / 单帧超时（秒）<input id="solverTimeout" type="number" min="10" max="1800" value="90"></label>
<p id="solverDetection"></p><p>Finding ASTAP does not verify its catalogue. 请用少量真实照片验证星表是否适用。</p>
<h3>Optional equipment corrections / 可选设备名称校正</h3>
<p>Use only if FITS TELESCOP is incorrect. Applies to a folder and its descendants; preserves original headers. 最具体的目录规则优先，FITS 原值始终保留。</p>
<div id="deviceRules"></div><button type="button" id="addDeviceRule">Add correction / 添加校正</button>
<p id="catalogAvailability"></p><p id="settingsMessage" role="status"></p>
<button type="submit" class="primary">Save / 保存</button> <button type="button" id="closeSettings">Close / 关闭</button></form>`;
document.body.append(setupPanel);
const setupButton=document.createElement('button');setupButton.textContent='Settings / 设置';setupButton.id='openSettings';
document.querySelector('header').append(setupButton);
let localSettings;
function renderDeviceRules(){
    const box=document.querySelector('#deviceRules');box.replaceChildren();
    for(const rule of localSettings.device_overrides){
        const row=document.createElement('div');row.className='deviceRule';
        const path=document.createElement('input');path.value=rule.path;path.placeholder='Absolute folder path / 目录完整路径';path.setAttribute('aria-label','Correction folder / 校正目录');path.oninput=()=>rule.path=path.value;
        const name=document.createElement('input');name.value=rule.telescope;name.placeholder='Telescope display name / 镜筒显示名称';name.setAttribute('aria-label','Telescope display name / 镜筒显示名称');name.oninput=()=>rule.telescope=name.value;
        const remove=document.createElement('button');remove.type='button';remove.textContent='Remove / 移除';remove.onclick=()=>{localSettings.device_overrides=localSettings.device_overrides.filter(x=>x!==rule);renderDeviceRules()};
        row.append(path,name,remove);box.append(row);
    }
}
async function readSetup(){
    const data=await api('/api/settings');localSettings=data.settings;
    for(const [id,key] of [['solverExecutable','executable'],['solverCatalog','catalog_dir'],['solverDatabase','database'],['solverTimeout','timeout']])document.getElementById(id).value=localSettings.solver[key];
    document.querySelector('#solverDetection').textContent=data.solver.executable_found?'Found / 已找到：'+data.solver.resolved_executable:'ASTAP not detected / 未找到 ASTAP；仍可索引和读取有效 WCS。';
    document.querySelector('#catalogAvailability').textContent=data.catalog_cached?'Object label catalogue cached / 已有天体标注目录':'Optional labels / 可选标注：运行 python build_catalogs.py 下载小型天体目录；完整说明见 README。';
    renderDeviceRules();
}
setupButton.onclick=async()=>{try{await readSetup();document.querySelector('#settingsMessage').textContent='';setupPanel.showModal()}catch(e){status(e.message)}};
document.querySelector('#addDeviceRule').onclick=()=>{localSettings.device_overrides.push({path:'',telescope:''});renderDeviceRules()};
document.querySelector('#closeSettings').onclick=()=>setupPanel.close();
document.querySelector('#settingsForm').onsubmit=async event=>{
    event.preventDefault();
    for(const [id,key] of [['solverExecutable','executable'],['solverCatalog','catalog_dir'],['solverDatabase','database']])localSettings.solver[key]=document.getElementById(id).value;
    localSettings.solver.timeout=Number(document.querySelector('#solverTimeout').value);
    try{await api('/api/settings',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(localSettings)});await readSetup();document.querySelector('#settingsMessage').textContent='Saved locally / 已保存到本机';await reload()}catch(e){document.querySelector('#settingsMessage').textContent=e.message}
};
(async()=>{
    const data=await api('/api/roots');
    if(!data.roots.length){
        document.querySelector('#sources').open=true;
        const welcome=document.createElement('section');welcome.className='welcome';welcome.id='welcome';
        welcome.innerHTML='<h2>Build your sky map<br>建立自己的天空地图</h2><ol><li>Add your local FITS folders below.<br>添加下面的本机目录。</li><li>Scan to index files and validated WCS.<br>扫描文件；有效 WCS 自动显示边界。</li><li>For files without WCS, configure ASTAP in Settings and scan with representative solving enabled.<br>无 WCS 时在设置中配置 ASTAP，再勾选代表帧解析。</li></ol><p>No example archive is preloaded. 首次使用从空档案开始；结果取决于你自己的照片。</p>';
        document.querySelector('#left').prepend(welcome);
    }
})().catch(e=>status(e.message));

let saves=[], curSave=null, curFile=null, user=null, ed=null, start=Date.now()

function login(){user={email:'admin@gmail.com'};document.getElementById('login').style.display='none';document.getElementById('app').style.display='flex';loadData()}
function register(){user={email:'admin@gmail.com'};document.getElementById('login').style.display='none';document.getElementById('app').style.display='flex';saves=[];renderSaves()}
function logout(){user=null;localStorage.clear();location.reload()}

function loadData(){let d=localStorage.getItem('saves');if(d){saves=JSON.parse(d);renderSaves()}}
function saveData(){localStorage.setItem('saves',JSON.stringify(saves))}

function renderSaves(){
let sel=document.getElementById('saveSelect');sel.innerHTML='<option value="">📁 Chọn Save</option>'
saves.forEach(s=>{sel.innerHTML+=`<option value="${s.id}">${s.name}</option>`})
renderFiles()
}

function renderFiles(){
let h='', s=curSave
if(s){s.files.forEach((f,i)=>{h+=`<div class="${i==curFile?'act':''}" onclick="loadFile(${i})">${f.name}<span style="color:#8b949e">${f.active?'✅':'❌'}</span></div>`})}
document.getElementById('fileList').innerHTML=h||'<div style="color:#8b949e;font-size:13px">Chưa có file</div>'
}

function loadSave(id){curSave=saves.find(s=>s.id==id);curFile=null;if(curSave&&curSave.files.length)loadFile(0);else if(ed){ed.setValue('// Chọn hoặc tạo file mới')}renderFiles();updateUI()}

function loadFile(i){if(!curSave)return;curFile=i;let f=curSave.files[i];ed.setValue(f.content);monaco.editor.setModelLanguage(ed.getModel(),f.lang||'plaintext');renderFiles();updateUI()}

function newSave(){let n=prompt('Tên Save:');if(!n)return;let id=Date.now()+'';saves.push({id,name:n,files:[],token:0,active:1,timer:0});saveData();renderSaves();loadSave(id)}

function renameSave(){if(!curSave)return;let n=prompt('Tên mới:',curSave.name);if(n){curSave.name=n;saveData();renderSaves()}}
function delSave(){if(!curSave||!confirm('Xóa?'))return;saves=saves.filter(s=>s.id!=curSave.id);curSave=null;curFile=null;saveData();renderSaves();if(ed)ed.setValue('// Chọn Save');updateUI()}

function addFile(){if(!curSave){alert('Chọn Save trước!');return}let n=prompt('Tên file (vd: test.py):');if(!n)return;let ext=n.split('.').pop()||'txt', map={js:'javascript',py:'python',cpp:'cpp',cs:'csharp',rb:'ruby',css:'css',html:'html',php:'php',json:'json'};curSave.files.push({id:Date.now()+'',name:n,content:'',lang:map[ext]||'plaintext',active:1});saveData();renderSaves();loadFile(curSave.files.length-1)}

function toggleToken(){if(!curSave)return;curSave.token=curSave.token?0:1;saveData();updateUI()}
function toggleActive(){if(!curSave)return;curSave.active=curSave.active?0:1;saveData();updateUI()}
function setTimer(v){if(!curSave)return;curSave.timer=parseInt(v);saveData();if(v>0)alert('⏰ Timer '+v+' phút!')}

function updateUI(){
if(!curSave){document.getElementById('tokenBtn').textContent='⚡ OFF';document.getElementById('tokenBtn').className='';document.getElementById('activeBtn').textContent='🕐 24/7';document.getElementById('activeBtn').className='';return}
let t=document.getElementById('tokenBtn');t.textContent='⚡ '+(curSave.token?'ON':'OFF');t.className=curSave.token?'on':''
let a=document.getElementById('activeBtn');a.textContent='🕐 '+(curSave.active?'ON':'OFF');a.className=curSave.active?'on':''
document.getElementById('saveSelect').value=curSave.id
}

require.config({paths:{vs:'https://cdnjs.cloudflare.com/ajax/libs/monaco-editor/0.34.1/min/vs'}})
require(['vs/editor/editor.main'],function(){ed=monaco.editor.create(document.getElementById('editor'),{value:'// Chọn Save để bắt đầu',language:'javascript',theme:'vs-dark',automaticLayout:true,lineNumbers:'on',fontSize:14,minimap:{enabled:false}})
ed.onDidChangeModelContent(()=>{updateStats();autoSave()})})

function updateStats(){if(!ed)return;let m=ed.getModel();if(!m)return;document.getElementById('lines').textContent=m.getLineCount();document.getElementById('chars').textContent=m.getValue().length}
function autoSave(){if(!curSave||curFile===null||!curSave.files[curFile])return;curSave.files[curFile].content=ed.getValue();saveData()}

setInterval(()=>{let e=Math.floor((Date.now()-start)/1000),h=String(Math.floor(e/3600)).padStart(2,'0'),m=String(Math.floor((e%3600)/60)).padStart(2,'0'),s=String(e%60).padStart(2,'0');document.getElementById('time').textContent=h+':'+m+':'+s},1000)

setInterval(()=>{if(!curSave||curFile===null||!curSave.files[curFile])return;let f=curSave.files[curFile], fr=document.getElementById('preview');if(f.lang=='html'){fr.src='data:text/html;charset=utf-8,'+encodeURIComponent(f.content)}else{fr.srcdoc='<html><body style="margin:0"><pre style="color:#fff;background:#0d1117;padding:20px;font-family:monospace;font-size:14px;white-space:pre-wrap;word-wrap:break-word">'+f.content+'</pre></body></html>'}},2000)

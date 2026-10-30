/* tris.json interactive viewer (no CDN, no three.js).
   Orthographic painter's sort canvas. Expects window.TRIS_URL set
   before load. Drag = rotate, wheel = zoom, buttons = presets. */
(function(){
  var canvas = document.getElementById('viewer3d');
  if (!canvas || !window.TRIS_URL) return;
  var ctx = canvas.getContext('2d');
  var bar = document.getElementById('viewerBar');
  var meta = document.getElementById('viewerMeta');
  var V=null,F=null,yaw=0.7,pitch=0.5,scale=1,cx=0,cy=0,cz=0,span=1;
  var dragging=false,lx=0,ly=0;
  function setBar(t){ if(bar) bar.textContent=t; }
  fetch(window.TRIS_URL).then(function(r){
    if(!r.ok) throw new Error('HTTP '+r.status); return r.json();
  }).then(function(j){
    V=j.verts; F=j.facets;
    var xmin=1e9,xmax=-1e9,ymin=1e9,ymax=-1e9,zmin=1e9,zmax=-1e9,i,p;
    for(i=0;i<V.length;i++){ p=V[i];
      if(p[0]<xmin)xmin=p[0]; if(p[0]>xmax)xmax=p[0];
      if(p[1]<ymin)ymin=p[1]; if(p[1]>ymax)ymax=p[1];
      if(p[2]<zmin)zmin=p[2]; if(p[2]>zmax)zmax=p[2]; }
    cx=(xmin+xmax)/2; cy=(ymin+ymax)/2; cz=(zmin+zmax)/2;
    span=Math.max(xmax-xmin,ymax-ymin,zmax-zmin)||1;
    draw();
    if(meta) meta.innerHTML='<span>verts</span><span>'+V.length+'</span>'
      +'<span>facets</span><span>'+F.length+'</span>'
      +'<span>bbox X</span><span>'+xmin.toFixed(2)+'..'+xmax.toFixed(2)+'</span>'
      +'<span>bbox Y</span><span>'+ymin.toFixed(2)+'..'+ymax.toFixed(2)+'</span>'
      +'<span>bbox Z</span><span>'+zmin.toFixed(2)+'..'+zmax.toFixed(2)+'</span>';
  }).catch(function(e){ setBar('3D load fail: '+e+' (see PNG below)'); });
  function rot(p){
    var x=p[0]-cx,y=p[1]-cy,z=p[2]-cz;
    var x1=x*Math.cos(yaw)-y*Math.sin(yaw);
    var y1=x*Math.sin(yaw)+y*Math.cos(yaw);
    var y2=y1*Math.cos(pitch)-z*Math.sin(pitch);
    var z2=y1*Math.sin(pitch)+z*Math.cos(pitch);
    return [x1,y2,z2];
  }
  function draw(){
    if(!V) return;
    var W=canvas.width,H=canvas.height,i,k,j;
    ctx.fillStyle='#0d1117'; ctx.fillRect(0,0,W,H);
    var base=Math.min(W,H-20)/span*0.9*scale;
    var items=[];
    for(i=0;i<F.length;i++){
      var a=F[i][0],b=F[i][1],c=F[i][2];
      if(a>=V.length||b>=V.length||c>=V.length) continue;
      var pa=rot(V[a]),pb=rot(V[b]),pc=rot(V[c]);
      var ux=pb[0]-pa[0],uy=pb[1]-pa[1],uz=pb[2]-pa[2];
      var vx=pc[0]-pa[0],vy=pc[1]-pa[1],vz=pc[2]-pa[2];
      var nx=uy*vz-uz*vy,ny=uz*vx-ux*vz,nz=ux*vy-uy*vx;
      var ln=Math.sqrt(nx*nx+ny*ny+nz*nz); if(!ln) continue;
      var shade=0.40+0.60*Math.max(0,nz/ln);
      items.push({d:(pa[2]+pb[2]+pc[2])/3,p:[pa,pb,pc],s:shade});
    }
    items.sort(function(m,n){return m.d-n.d;});
    for(k=0;k<items.length;k++){
      var it=items[k];
      ctx.fillStyle='rgb('+Math.round(174*it.s)+','+Math.round(191*it.s)+','+Math.round(214*it.s)+')';
      ctx.beginPath();
      for(j=0;j<3;j++){ var q=it.p[j];
        var sx=W/2+q[0]*base, sy=H/2-q[1]*base;
        if(j) ctx.lineTo(sx,sy); else ctx.moveTo(sx,sy); }
      ctx.closePath(); ctx.fill();
    }
    setBar('drag rotate - wheel zoom - '+F.length+' tris - yaw '+yaw.toFixed(2)+' pitch '+pitch.toFixed(2));
  }
  canvas.addEventListener('mousedown',function(e){dragging=true;lx=e.clientX;ly=e.clientY;});
  window.addEventListener('mouseup',function(){dragging=false;});
  canvas.addEventListener('mousemove',function(e){
    if(!dragging) return;
    yaw+=(e.clientX-lx)*0.008; pitch+=(e.clientY-ly)*0.008;
    pitch=Math.max(-1.4,Math.min(1.4,pitch));
    lx=e.clientX; ly=e.clientY; draw();
  });
  canvas.addEventListener('wheel',function(e){
    e.preventDefault();
    scale*=(e.deltaY<0?1.1:0.9); scale=Math.max(0.2,Math.min(8,scale)); draw();
  },{passive:false});
  var btns=document.querySelectorAll('.viewer-tools button');
  btns.forEach(function(b){
    b.addEventListener('click',function(){
      var v=b.getAttribute('data-view');
      if(v==='iso'){yaw=0.7;pitch=0.5;}
      else if(v==='main'){yaw=0;pitch=0;}
      else if(v==='top'){yaw=0;pitch=1.35;}
      else if(v==='side'){yaw=1.5708;pitch=0;}
      scale=1; draw();
    });
  });
})();

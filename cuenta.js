/* Cuenta de resultados de un vistazo: diagrama de flujo con las cifras de la SEC
   (data/<T>.json → resultados y segmentos). Lo usan valorador.html (Finanzas) y
   resultados.html (informe de cada trimestre). Sin dependencias. */
(function(){
const fin=x=>typeof x==="number"&&isFinite(x);
const M6=1e6;
const esc=s=>String(s==null?"":s).replace(/[&<>"']/g,c=>({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"}[c]));
const nf=(v,d=0)=>fin(v)?v.toLocaleString("en-US",{minimumFractionDigits:d,maximumFractionDigits:d}).replace(/[,.]/g,c=>c===","?".":","):"–";
const pct=(v,d=1)=>fin(v)?nf(v,d)+"%":"–";
const SEG={"Product Sales":"Ventas de producto","Product and Service, Other":"Otros ingresos","Stand-Ready Manufacturing":"Fabricación reservada","Stand-Ready Manufacturing Revenue":"Fabricación reservada","Collaboration Arrangement, Including Arrangements With Affiliate":"Colaboraciones","Grant":"Subvenciones","License and Royalty":"Licencias y regalías","RSV":"VRS"};
/* ================= CUENTA DE RESULTADOS DE UN VISTAZO (diagrama de flujo, SEC) ================= */
function skLabYA(lab){ const m=/^(\d)T(\d{2})$/.exec(lab||""); return m?`${m[1]}T${String(+m[2]-1).padStart(2,"0")}`:/^\d{4}$/.test(lab||"")?String(+lab-1):null; }
function skPeriods(D){
  const R=(D&&D.resultados)||{}, I=R.ingresos||{}, q=(I.trimestral||[]).at(-1), a=(I.anual||[]).at(-1), t=I.ttm;
  const out=[]; if(q) out.push({id:"q",t:"q",lab:q.periodo,name:"Último trimestre · "+q.periodo,url:q.url,fecha:q.fecha_presentacion,form:q.formulario});
  if(t&&t.derivado) out.push({id:"ttm",t:"ttm",labs:t.derivado.split(/\s*\+\s*/),lab:"UDM",name:"Últimos 12 meses",url:t.url,fecha:t.fecha_presentacion,form:"suma de 4 trimestres"});
  if(a) out.push({id:"a",t:"a",lab:a.periodo,name:"Año "+a.periodo,url:a.url,fecha:a.fecha_presentacion,form:a.formulario});
  return out;
}
function skGet(D,k,per,lab){ /* valor en M de un concepto para un periodo (q/a: etiqueta; ttm: suma de 4 trimestres) */
  const r=((D&&D.resultados)||{})[k]; if(!r) return NaN;
  const one=(list,l)=>{ const p=(list||[]).find(x=>x.periodo===l); return p?p.valor/M6:NaN; };
  if(per.t==="ttm"){ let s=0; for(const l of per.labs){ const v=one(r.trimestral,l); if(!fin(v)) return NaN; s+=v; } return s; }
  return one(per.t==="a"?r.anual:r.trimestral, lab||per.lab);
}
function skSga(D,per,lab){ /* SG&A: total si existe; si no, ventas + generales. En UDM, trimestre a trimestre */
  const f=(p,l)=>{ const g=skGet(D,"gastos_generales",p,l); if(fin(g)) return g; const v=skGet(D,"ventas_marketing",p,l), a=skGet(D,"gastos_admin",p,l); return fin(v)||fin(a)?(fin(v)?v:0)+(fin(a)?a:0):NaN; };
  if(per.t==="ttm"){ let s=0; for(const l of per.labs){ const v=f({t:"q"},l); if(!fin(v)) return NaN; s+=v; } return s; }
  return f(per,lab);
}
function skYoy(r){ if(!fin(r)||r<=0) return ""; return r>4?"×"+nf(r,0)+" interanual":pct((r-1)*100,0)+" interanual"; }
function skSegments(D,per,rev,segName){ /* combinación de segmentos o productos que suma los ingresos (±2,5%) */
  const S=D&&D.segmentos; if(!S||!fin(rev)||rev<=0) return null;
  const val=x=>{ const one=(l,use)=>{ const p=(x[use]||[]).find(p=>p.periodo===l); return p?p.valor/M6:NaN; };
    if(per.t==="ttm"){ let s=0; for(const l of per.labs){ const v=one(l,"trimestral"); if(!fin(v)) return NaN; s+=v; } return s; }
    return one(per.lab,per.t==="a"?"anual":"trimestral"); };
  for(const grp of ["segmento","producto"]){
    const it=(S[grp]||[]).filter(x=>!x.ajuste).map(x=>({n:segName(x.nombre),v:val(x)})).filter(x=>fin(x.v)&&x.v>0).slice(0,14);
    if(!it.length) continue; let best=null;
    for(let m=1;m<(1<<it.length);m++){ let s=0,c=0; for(let i=0;i<it.length;i++) if(m&(1<<i)){s+=it[i].v;c++;}
      const e=Math.abs(s/rev-1); if(e>0.025) continue; const b=e<=0.001?0:e<=0.004?1:2;
      const er=Math.round(e*5000); if(!best||b<best.b||(b===best.b&&(er<best.er||(er===best.er&&c>best.c)))) best={m,c,b,er}; }
    if(best){ let rows=it.filter((_,i)=>best.m&(1<<i)).sort((a,b)=>b.v-a.v);
      if(rows.length>6){ const o=rows.slice(5).reduce((a,r)=>a+r.v,0); rows=rows.slice(0,5).concat([{n:"Otros",v:o}]); }
      return rows.length>1?rows:null; }
  }
  return null;
}
function skModel(D,per,segName){
  const g=k=>skGet(D,k,per), rev=g("ingresos"); if(!fin(rev)||rev<=0) return null;
  let cogs=g("coste_ventas"); const gb=g("beneficio_bruto"); if(!fin(cogs)&&fin(gb)) cogs=rev-gb;
  const op=g("beneficio_operativo"), net=g("beneficio_neto"); if(!fin(op)||!fin(net)) return null;
  const tax=fin(g("impuestos"))?g("impuestos"):0, rd=g("investigacion_desarrollo");
  const gg=per.t==="ttm"?NaN:g("gastos_generales"), vm=per.t==="ttm"?NaN:g("ventas_marketing"), ga=per.t==="ttm"?NaN:g("gastos_admin");
  const sgaRows=fin(gg)?[["Comerciales y generales",gg]]:(fin(vm)||fin(ga))?[["Ventas y marketing",vm],["Generales y administración",ga]]:[["Comerciales y generales",skSga(D,per)]];
  const gp=fin(cogs)?rev-cogs:NaN, opex=(fin(gp)?gp:rev)-op;
  let items=[["I+D",rd],...sgaRows].filter(([,v])=>fin(v)&&v>0).map(([n,v])=>({n,v}));
  let rest=opex-items.reduce((a,x)=>a+x.v,0);
  if(rest<-Math.max(1,opex*0.02)){ items=[]; rest=opex; }   /* las partidas no cuadran: un solo bloque */
  if(rest>Math.max(0.5,opex*0.005)) items.push({n:fin(gp)?"Otros gastos operativos":"Otros costes operativos",v:rest});
  const nonop=net+tax-op;   /* intereses, otros no operativos, minoritarios… */
  const ya=per.t==="ttm"?null:skLabYA(per.lab), y=k=>ya?skGet(D,k,per,ya):NaN;
  return {rev,cogs,gp,op,opex,items,net,tax,nonop,yoyRev:fin(y("ingresos"))&&y("ingresos")>0?(rev/y("ingresos")-1)*100:NaN,
    segs:skSegments(D,per,rev,segName), segYA:ya?skSegments(D,{...per,lab:ya},y("ingresos"),segName):null};
}
function skSvg(M,C){
  C=C||{};
  const W=C.w||1000, H=C.h||470, top=44, bot=14, gap=C.gap||46, nw=14;
  const GOOD=C.good||"var(--good)", BAD=C.bad||"var(--crit)", REV=C.rev||"var(--c1,#2C6FAC)", LOSS=C.loss||"var(--critText)", INK=C.ink||"var(--ink)", INK2=C.ink2||"var(--ink2)", MUT=C.muted||"var(--muted)";
  const nodes=[], flows=[];
  const N=(id,col,v,lab,color,sub)=>{ nodes.push({id,col,v:Math.max(v,0),lab,color,sub}); return id; };
  const F=(a,b,v,color)=>{ if(v>0) flows.push({a,b,v,color}); };
  const m=v=>pct(v/M.rev*100,0), seg=M.segs, c0=seg?0:-1;
  if(seg) seg.forEach((s,i)=>{ const p=(M.segYA||[]).find(x=>x.n===s.n); N("s"+i,0,s.v,s.n,REV,p&&p.v>0?skYoy(s.v/p.v):""); F("s"+i,"rev",s.v,REV); });
  N("rev",1,M.rev,"Ingresos",REV,fin(M.yoyRev)?skYoy(1+M.yoyRev/100):"");
  const loss=M.op<0;
  if(fin(M.gp)&&M.gp>0&&!loss){
    N("gp",2,M.gp,"Beneficio bruto",GOOD,"margen "+m(M.gp)); N("cogs",2,M.cogs,"Coste de ventas",BAD,"");
    F("rev","gp",M.gp,GOOD); F("rev","cogs",M.cogs,BAD);
    N("op",3,M.op,"Beneficio operativo",GOOD,"margen "+m(M.op)); if(M.nonop>0&&M.op>=0) N("nonopIn",3,M.nonop,"Otros ingresos",GOOD,"intereses y otros"); N("opex",3,M.opex,"Gastos operativos",BAD,"");
    F("gp","op",M.op,GOOD); F("gp","opex",M.opex,BAD);
  } else if(!loss){
    N("op",3,M.op,"Beneficio operativo",GOOD,"margen "+m(M.op)); if(M.nonop>0) N("nonopIn",3,M.nonop,"Otros ingresos",GOOD,"intereses y otros"); N("opex",3,M.opex,"Costes operativos",BAD,"");
    F("rev","op",M.op,GOOD); F("rev","opex",M.opex,BAD);
  }
  if(!loss){
    const extra=M.nonop>0?M.nonop:0;
    N("net",4,M.net,M.net>=0?"Beneficio neto":"Pérdida neta",M.net>=0?GOOD:BAD,M.net>=0?"margen "+m(M.net):"");
    if(M.tax>0) N("tax",4,M.tax,"Impuestos",BAD,"");
    if(M.nonop<0) N("nonopOut",4,-M.nonop,"Otros gastos",BAD,"intereses y otros");
    const nP=Math.max(M.net,0), oN=Math.min(M.op,nP), iN=nP-oN; let rO=M.op-oN, rI=extra-iN;
    F("op","net",oN,GOOD); if(extra) F("nonopIn","net",iN,GOOD);
    const tO=Math.min(M.tax,Math.max(rO,0)); F("op","tax",tO,BAD); rO-=tO; if(extra) { F("nonopIn","tax",Math.min(M.tax-tO,rI),BAD); }
    if(M.nonop<0) F("op","nonopOut",Math.max(rO,0),BAD);
    M.items.forEach((x,i)=>{ N("x"+i,4,x.v,x.n,BAD,m(x.v)+" de ingresos"); F("opex","x"+i,x.v,BAD); });
  } else {
    const costs=(fin(M.cogs)?M.cogs:0)+M.opex+(fin(M.gp)?0:0);
    N("lossop",1,-M.op,"Pérdida operativa",LOSS,"margen "+m(M.op));
    N("costs",2,M.rev-M.op,"Costes y gastos",BAD,"");
    F("rev","costs",M.rev,BAD); F("lossop","costs",-M.op,LOSS);
    if(fin(M.cogs)&&M.cogs>0){ N("cogs",3,M.cogs,"Coste de ventas",BAD,m(M.cogs)+" de ingresos"); F("costs","cogs",M.cogs,BAD); }
    M.items.forEach((x,i)=>{ N("x"+i,3,x.v,x.n,BAD,m(x.v)+" de ingresos"); F("costs","x"+i,x.v,BAD); });
    N("net",4,Math.abs(M.net),M.net>=0?"Beneficio neto":"Pérdida neta",M.net>=0?GOOD:LOSS,(M.nonop>=0?"+":"−")+nf(Math.abs(M.nonop))+" no operativo · "+nf(M.tax)+" impuestos");
  }
  /* columnas: x y escala común */
  const cols=[...new Set(nodes.map(n=>n.col))].sort((a,b)=>a-b), X={}; const tw=n=>Math.max((String(n.lab).length+nf(n.v).length+1)*7.4,String(n.sub||"").length*6.4)+16;
  const L=seg?Math.min(280,Math.max(110,...nodes.filter(n=>n.col===0).map(tw))):30, Rm=Math.min(320,Math.max(150,...nodes.filter(n=>n.col===Math.max(...nodes.map(x=>x.col))).map(tw)));
  cols.forEach((c,i)=>{ X[c]=L+(W-L-Rm)*(cols.length>1?i/(cols.length-1):0); });
  const by=c=>nodes.filter(n=>n.col===c), tot=c=>by(c).reduce((a,n)=>a+n.v,0);
  const k=Math.min(...cols.map(c=>(H-top-bot-gap*(by(c).length-1))/Math.max(tot(c),1e-9)));
  cols.forEach(c=>{ const ns=by(c), h=tot(c)*k+gap*(ns.length-1); let y=top+(H-top-bot-h)/2;
    ns.forEach(n=>{ n.x=X[c]; n.y=y; n.h=Math.max(n.v*k,1.5); n.o=0; n.i=0; y+=n.h+gap; }); });
  const byId=Object.fromEntries(nodes.map(n=>[n.id,n]));
  const paths=flows.map(f=>{ const A=byId[f.a], B=byId[f.b]; if(!A||!B) return ""; const h=f.v*k;
    const y0=A.y+A.o, y1=B.y+B.i; A.o+=h; B.i+=h; const x0=A.x+nw, x1=B.x, cx=(x0+x1)/2;
    return `<path d="M${x0},${y0} C${cx},${y0} ${cx},${y1} ${x1},${y1} L${x1},${y1+h} C${cx},${y1+h} ${cx},${y0+h} ${x0},${y0+h} Z" fill="${f.color}" opacity=".28"><title>${esc(A.lab)} → ${esc(B.lab)}: ${nf(f.v)}</title></path>`; }).join("");
  const lastCol=cols.at(-1); let ly=-1e9; const boxes=[];
  const labs=nodes.map(n=>{ const val=nf(n.v), first=n.col===cols[0]&&seg;
    if(n.col===lastCol||first){ let cy=n.y+n.h/2; if(!first){ cy=Math.max(cy,ly+30); ly=cy; }
      const x=first?n.x-8:n.x+nw+8, a=first?"end":"start";
      return `<text x="${x}" y="${cy-3}" text-anchor="${a}" font-size="12.5" font-weight="700" fill="${INK}">${esc(n.lab)} <tspan font-family="JetBrains Mono,monospace" font-weight="600">${val}</tspan></text>${n.sub?`<text x="${x}" y="${cy+12}" text-anchor="${a}" font-size="11" fill="${MUT}">${esc(n.sub)}</text>`:""}`; }
    let ty=n.y-20; const w=Math.max(String(n.lab).length*7.4,(val.length+(n.sub?n.sub.length+3:0))*7)/2;
    for(let k=0;k<4;k++){ const hit=boxes.find(b=>Math.abs(b.x-(n.x+nw/2))<b.w+w+6&&Math.abs(b.y-ty)<30); if(!hit) break; ty=hit.y-32; }
    boxes.push({x:n.x+nw/2,y:ty,w});
    return `<text x="${n.x+nw/2}" y="${ty}" text-anchor="middle" font-size="12.5" font-weight="700" fill="${INK}">${esc(n.lab)}</text><text x="${n.x+nw/2}" y="${ty+14}" text-anchor="middle" font-size="11.5" font-family="JetBrains Mono,monospace" fill="${INK2}">${val}${n.sub?` · ${esc(n.sub)}`:""}</text>`; }).join("");
  const rects=nodes.map(n=>`<rect x="${n.x}" y="${n.y}" width="${nw}" height="${n.h}" rx="2" fill="${n.color}"><title>${esc(n.lab)}: ${nf(n.v)}</title></rect>`).join("");
  return `<svg viewBox="0 0 ${W} ${H}" role="img" aria-label="Diagrama de la cuenta de resultados" style="width:100%;height:auto;${C.minw===0?"":"min-width:640px"}">${paths}${rects}${labs}</svg>`;
}

window.Cuenta={
  SEG,
  periods:skPeriods,
  /* per: {t:"q"|"a"|"ttm", lab, labs}; opts: {segName, colors} → {model, svg} o null */
  build(D,per,opts){ opts=opts||{}; const sn=n=>SEG[n]||(opts.segName?opts.segName(n):n);
    const M=skModel(D,per,sn); return M?{model:M,svg:skSvg(M,opts.colors)}:null; }
};
})();

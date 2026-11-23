/* Valorador de compañías: motor del DCF y escenarios (lo usa también scripts/impacto_dcf.mjs). */
// ENGINE START
function project(s, adj){
  adj = adj || {dg:0, dm:0};
  const yrs=[]; let rev=s.rev0, prev=s.rev0;
  for(let i=0;i<5;i++){
    const g=(s.g[i]+adj.dg)/100;
    rev=prev*(1+g);
    const m=((s.m1+(s.m5-s.m1)*i/4)+adj.dm)/100;
    const lerp=(a,b)=>a+((b??a)-a)*i/4;
    const ebitda=rev*m, da=rev*lerp(s.da,s.da5)/100, sbc=rev*s.sbc/100;
    const ebit=ebitda-da-sbc, tax=Math.max(0,ebit)*s.tax/100;
    const capex=rev*lerp(s.capex,s.capex5)/100, dnwc=(rev-prev)*s.nwc/100;
    const fcf=ebit-tax+da-capex-dnwc;
    yrs.push({year:s.year0+i+1, g, rev, m, ebitda, da, sbc, ebit, tax, capex, dnwc, fcf});
    prev=rev;
  }
  return yrs;
}
/* Del valor de empresa al del accionista. Caja y deuda de la SEC; además, las participaciones
   en no cotizadas (no están en la caja ni en los flujos) menos el impuesto latente de su
   revalorización, y las preferentes, que son de otros inversores. */
const TAX_LATENTE=21; /* tipo federal de EE. UU. sobre plusvalías de sociedades; no el tipo efectivo, que lleva deducciones */
function invNet(s){ const inv=s.inv>0?s.inv:0, g=s.invGain>0?s.invGain:0; return inv-Math.min(inv,g)*TAX_LATENTE/100; }
function netDebtV(s){ return s.debt+(s.pref>0?s.pref:0)-s.cash-invNet(s); }
function dcf(s, opt){
  opt=opt||{};
  const w=(opt.wacc??s.wacc)/100, tg=(opt.tg??s.tg)/100, mult=opt.exit??s.exit;
  const method=opt.method??s.method;
  const yrs=project(s,opt.adj);
  let pv=0; yrs.forEach((y,i)=>{y.df=1/Math.pow(1+w,i+1); y.pv=y.fcf*y.df; pv+=y.pv;});
  const last=yrs[4];
  const tvG = w>tg ? last.fcf*(1+tg)/(w-tg) : NaN;
  const tvM = last.ebitda*mult;
  const tv = method==='gordon'?tvG : method==='exit'?tvM : (tvG+tvM)/2;
  const pvTV = tv*last.df;
  const ev=pv+pvTV, eq=ev-netDebtV(s), ps=eq/s.shares;
  return {yrs, pv, tv, pvTV, ev, eq, ps, tvShare:pvTV/ev, impliedExit:tv/last.ebitda, impliedG:(tv*w-last.fcf)/(tv+last.fcf)};
}
function impliedGrowth(s){
  const f=g=>dcf(Object.assign({},s,{g:[g,g,g,g,g]})).ps - s.price;
  let lo=-40, hi=150;
  if(!isFinite(f(lo))||!isFinite(f(hi))||f(lo)>0||f(hi)<0) return NaN;
  for(let i=0;i<80;i++){const mid=(lo+hi)/2; if(f(mid)>0) hi=mid; else lo=mid;}
  return (lo+hi)/2;
}
function scenarios(s){
  const out=s.scn.map(c=>({...c, ps:dcf(s,{adj:{dg:c.dg,dm:c.dm}}).ps}));
  const tp=out.reduce((a,c)=>a+c.p,0);
  const w=tp>0?out.reduce((a,c)=>a+c.ps*c.p,0)/tp:NaN;
  return {out, tp, w};
}
// ENGINE END

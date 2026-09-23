(function(){
  var tip=document.getElementById('tip'),cur=null;
  function show(el){
    tip.textContent=el.getAttribute('data-tip');tip.hidden=false;cur=el;
    var r=el.getBoundingClientRect(),w=tip.offsetWidth,h=tip.offsetHeight;
    var x=Math.max(8,Math.min(r.left+r.width/2-w/2,innerWidth-w-8));
    var y=r.bottom+8;if(y+h>innerHeight-8)y=Math.max(8,r.top-h-8);
    tip.style.left=x+'px';tip.style.top=y+'px';
  }
  function hide(){tip.hidden=true;cur=null;}
  document.addEventListener('mouseover',function(e){var q=e.target.closest('.q');if(q)show(q);});
  document.addEventListener('mouseout',function(e){if(e.target.closest('.q'))hide();});
  document.addEventListener('focusin',function(e){var q=e.target.closest('.q');
    if(q&&q.matches(':focus-visible'))show(q);});
  document.addEventListener('focusout',hide);
  document.addEventListener('click',function(e){var q=e.target.closest('.q');if(q)show(q);else hide();});
  document.addEventListener('keydown',function(e){if(e.key==='Escape')hide();});
  addEventListener('scroll',function(){if(cur)hide();},{passive:true});
})();

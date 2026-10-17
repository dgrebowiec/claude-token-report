(function(){
  // a click on a session row in "Heaviest conversations" shows or hides its details
  function toggle(row){
    var det=row.nextElementSibling,btn=row.querySelector('.sbtn');
    if(!det||!det.classList.contains('sdet'))return;
    det.hidden=!det.hidden;row.classList.toggle('open',!det.hidden);
    if(btn)btn.setAttribute('aria-expanded',String(!det.hidden));
  }
  document.addEventListener('click',function(e){
    if(e.target.closest('.q'))return;
    var row=e.target.closest('tr.sess');if(row)toggle(row);
  });
})();

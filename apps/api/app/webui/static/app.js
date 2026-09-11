/* MSB серверный UI — общий клиентский JS.
   Динамика — на HTMX; здесь только меню, модалки, тосты и мелкие хелперы. */
function msbOpenMenu(){ document.getElementById('sidebar').classList.add('open');
  document.getElementById('backdrop').classList.add('show'); }
function msbCloseMenu(){ var s=document.getElementById('sidebar'); if(s) s.classList.remove('open');
  var b=document.getElementById('backdrop'); if(b) b.classList.remove('show'); }

function msbToast(text, kind){
  kind = kind || 'ok';
  var slot = document.getElementById('flash-slot');
  if(!slot){ alert(text); return; }
  var d = document.createElement('div');
  d.className = 'flash ' + (kind === 'err' ? 'err' : kind === 'info' ? 'info' : 'ok');
  d.textContent = text;
  slot.appendChild(d);
  setTimeout(function(){ d.style.opacity = '0'; d.style.transition = 'opacity .4s'; }, 3500);
  setTimeout(function(){ d.remove(); }, 4100);
}

// Простейшая модалка: контент подгружается по URL (HTMX) либо передаётся готовым.
function msbOpenModal(html){
  msbCloseModal();
  var ov = document.createElement('div');
  ov.className = 'modal-overlay'; ov.id = 'modal-overlay';
  ov.innerHTML = '<div class="modal" id="modal-box"></div>';
  ov.addEventListener('click', function(e){ if(e.target === ov) msbCloseModal(); });
  document.body.appendChild(ov);
  document.body.style.overflow = 'hidden';
  var box = document.getElementById('modal-box');
  if(html) box.innerHTML = html;
  document.addEventListener('keydown', msbEscClose);
  return box;
}
function msbCloseModal(){
  var ov = document.getElementById('modal-overlay');
  if(ov) ov.remove();
  document.body.style.overflow = '';
  document.removeEventListener('keydown', msbEscClose);
}
function msbEscClose(e){ if(e.key === 'Escape') msbCloseModal(); }

// Подтверждение для ссылок с data-confirm (удаление и т.п.)
document.addEventListener('click', function(e){
  var el = e.target.closest('[data-confirm]');
  if(el && !confirm(el.getAttribute('data-confirm'))){ e.preventDefault(); e.stopPropagation(); }
});

// После HTMX-действий с атрибутом data-toast показываем сообщение.
document.body.addEventListener('htmx:afterRequest', function(evt){
  var trig = evt.detail.requestConfig && evt.detail.triggeringEvent;
  var el = evt.target;
  if(evt.detail.successful){
    var msg = el.getAttribute && el.getAttribute('data-toast');
    if(msg){ msbToast(msg); }
    // Закрыть модалку, если действие помечено data-close-modal
    if(el.closest && el.closest('[data-close-modal]')){ msbCloseModal(); }
  } else if(evt.detail.xhr && evt.detail.xhr.status === 401){
    window.location.href = '/login';
  }
});

// Авто-закрытие мобильного меню после перехода
document.addEventListener('htmx:afterOnLoad', function(){ msbCloseMenu(); });

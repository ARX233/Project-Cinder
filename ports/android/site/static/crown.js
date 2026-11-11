(() => {
  const box = document.getElementById('kings');
  const stage = document.getElementById('crown-stage');
  const display = document.getElementById('crown-display');
  const motion = document.getElementById('crown-motion');
  const plates = document.getElementById('crown-plates');
  const reduced = matchMedia('(prefers-reduced-motion: reduce)');
  let paused = reduced.matches;
  let current;
  let areas = [];
  let tour = [];
  let timer;

  function esc(value) {
    return String(value ?? '').replace(/[&<>"']/g, c =>
      ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
  }

  function card(king) {
    const course = esc(king.course_name);
    if (king.idle) {
      return `<article class="card king-card empty">
        <div class="course">${course}</div>
        <div class="who dim">虚位以待</div>
        <div class="slot">还没有成绩</div>
      </article>`;
    }
    return `<article class="card king-card">
      <div class="course">${course}</div>
      <div class="who">${esc(king.name)}</div>
      <div class="carlabel">${esc(king.car || '车型未知')}</div>
      <div class="meta">
        <div><span>马力</span><b>${esc(king.hp ?? '—')}${king.hp == null ? '' : ' PS'}</b></div>
        <div><span>获得时间 · UTC+8</span><b>${esc(king.acquired_at)}</b></div>
      </div>
      <button class="chip crown-view" type="button" data-course="${esc(king.course)}">在展台查看</button>
    </article>`;
  }

  function show(king) {
    current = king;
    const position = areas.findIndex(item => item.area === king.area);
    plates.src = `/crown/plate-${position}.webp`;
    document.querySelectorAll('#crown-areas button').forEach((button, i) => {
      button.setAttribute('aria-pressed', String(i === position));
    });
    const preview = /^\/crown\/car-(?:\d+-){8}\d+\.webp$/.test(king.preview) ? king.preview : null;
    const poster = /^\/crown\/(?:car-(?:\d+-){8}\d+-still|stock-\d+)\.webp$/.test(king.preview_still)
      ? king.preview_still : preview && preview.replace('.webp', '-still.webp');
    const stock = poster && poster.startsWith('/crown/stock-');
    display.innerHTML = `<div class="crown-driver">
      <div class="crown-course">${esc(king.course_name)}</div>
      <h2>${king.idle ? '虚位以待' : esc(king.name)}</h2>
      <p>${king.idle ? '等待首位挑战者' : esc(king.car || '车型未知')}${king.hp == null ? '' : ` · ${esc(king.hp)} PS`}</p>
    </div>${poster ? `<img class="crown-car" src="${poster}" fetchpriority="high" alt="${esc(king.car)}${stock ? ' 原厂车型预览' : ' 的本场车辆外观'}">
      ${stock ? '<p class="crown-stock-note">原厂车型预览</p>' : ''}`
      : king.idle ? '' : '<p class="crown-no-preview">本场车辆外观暂不可展示</p>'}`;
    motion.textContent = paused ? '播放动画' : '暂停动画';
    if (preview && !paused) loadAnimation(display.querySelector('.crown-car'), preview);
  }

  async function loadAnimation(poster, preview) {
    // Show the small still before starting the larger animation request.
    await poster.decode().catch(() => {});
    if (!poster.isConnected) return;
    const animation = new Image();
    animation.fetchPriority = 'low';
    animation.src = preview + '?v=3';
    try {
      await animation.decode();
    } catch {
      return; // Keep the still if the animation is unavailable.
    }
    if (!poster.isConnected) return;
    animation.className = poster.className;
    animation.alt = poster.alt;
    animation.style.animation = 'none';
    poster.replaceWith(animation);
  }

  function schedule() {
    clearInterval(timer);
    if (paused || tour.length < 2) return;
    timer = setInterval(() => {
      const index = tour.findIndex(king => king.course === current.course);
      show(tour[(index + 1) % tour.length]);
    }, 7000);
  }

  const picker = document.getElementById('crown-areas');
  let loading = false;
  function select(king) {
    if (!king) return;
    show(king);
    schedule();
  }

  box.addEventListener('click', event => {
    const button = event.target.closest('.crown-view');
    if (!button) return;
    select(areas.find(item => String(item.course) === button.dataset.course));
    stage.scrollIntoView({ block: 'start', behavior: paused ? 'instant' : 'smooth' });
  });
  motion.addEventListener('click', () => {
    paused = !paused;
    select(current);
  });
  reduced.addEventListener('change', event => {
    paused = event.matches;
    select(current);
  });

  async function load() {
    if (loading || document.hidden) return;
    loading = true;
    try {
      const response = await fetch('/api/ghost', { cache: 'no-store' });
      if (!response.ok) throw new Error('Crown request failed');
      const { kings } = await response.json();
      if (!kings.length || JSON.stringify(areas) === JSON.stringify(kings)) return;
      if (!areas.length) {
        kings.forEach(king => {
          const button = document.createElement('button');
          button.type = 'button';
          button.textContent = king.course_name;
          button.addEventListener('click', () => select(areas.find(item => item.area === king.area)));
          picker.append(button);
        });
      }
      areas = kings;
      tour = kings.filter(king => !king.idle);
      box.innerHTML = kings.map(card).join('');
      select(kings.find(king => king.area === current?.area) || tour[0] || kings[0]);
      stage.hidden = false;
    } catch (error) {
      if (!areas.length) box.innerHTML = '<div class="card"><p>载入失败，请稍后重试。</p></div>';
    } finally {
      loading = false;
    }
  }

  document.addEventListener('visibilitychange', load);
  setInterval(load, 15000);
  load();
})();

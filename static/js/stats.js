/**
 * Page /stats — récit en chapitres (count-up, dots, Intersection Observer).
 * Chart.js reste inline : il a besoin des libellés traduits et du payload Jinja.
 */
(function () {
    const reduce = window.matchMedia('(prefers-reduced-motion: reduce)').matches;
    const counted = new WeakSet();

    function formatMinutes(total) {
        total = Math.max(0, Math.round(total));
        const days = Math.floor(total / (60 * 24));
        const rem = total % (60 * 24);
        const hours = Math.floor(rem / 60);
        const minutes = rem % 60;
        if (days) return days + 'j ' + hours + 'h ' + String(minutes).padStart(2, '0') + 'm';
        if (hours) return hours + 'h ' + String(minutes).padStart(2, '0') + 'm';
        return minutes + ' min';
    }

    function animateCount(el) {
        if (counted.has(el)) return;
        counted.add(el);
        const target = parseFloat(el.getAttribute('data-count') || '0');
        const decimals = parseInt(el.getAttribute('data-decimals') || '0', 10);
        const suffix = el.getAttribute('data-suffix') || '';
        if (reduce || !isFinite(target)) {
            el.textContent = (decimals ? target.toFixed(decimals) : String(Math.round(target))) + suffix;
            return;
        }
        const duration = 1100;
        const start = performance.now();
        function frame(now) {
            const t = Math.min(1, (now - start) / duration);
            const eased = 1 - Math.pow(1 - t, 3);
            const val = target * eased;
            el.textContent = (decimals ? val.toFixed(decimals) : String(Math.round(val))) + suffix;
            if (t < 1) requestAnimationFrame(frame);
        }
        requestAnimationFrame(frame);
    }

    function animateMinutes(el) {
        if (counted.has(el)) return;
        counted.add(el);
        const target = parseFloat(el.getAttribute('data-count-minutes') || '0');
        if (reduce || !isFinite(target)) {
            el.textContent = formatMinutes(target);
            return;
        }
        const duration = 1200;
        const start = performance.now();
        function frame(now) {
            const t = Math.min(1, (now - start) / duration);
            const eased = 1 - Math.pow(1 - t, 3);
            el.textContent = formatMinutes(target * eased);
            if (t < 1) requestAnimationFrame(frame);
            else el.textContent = formatMinutes(target);
        }
        requestAnimationFrame(frame);
    }

    function activateChapter(chapter) {
        chapter.querySelectorAll('.reveal').forEach((r) => r.classList.add('is-in'));
        chapter.querySelectorAll('[data-count]').forEach(animateCount);
        chapter.querySelectorAll('[data-count-minutes]').forEach(animateMinutes);
        chapter.querySelectorAll('[data-bar]').forEach((bar) => {
            bar.style.width = (bar.getAttribute('data-bar') || '0') + '%';
        });
    }

    function setActiveDot(id) {
        document.querySelectorAll('.stats-dots a').forEach((a) => {
            a.classList.toggle('is-active', a.getAttribute('data-dot') === id);
        });
    }

    const dotIo = new IntersectionObserver((entries) => {
        entries.forEach((entry) => {
            if (!entry.isIntersecting) return;
            setActiveDot(entry.target.id);
        });
    }, { threshold: 0.45 });

    document.querySelectorAll('.stats-chapter').forEach((ch) => dotIo.observe(ch));

    if (reduce) {
        document.querySelectorAll('.stats-chapter').forEach(activateChapter);
        return;
    }

    const chapterIo = new IntersectionObserver((entries) => {
        entries.forEach((entry) => {
            if (!entry.isIntersecting) return;
            activateChapter(entry.target);
            chapterIo.unobserve(entry.target);
        });
    }, { threshold: 0.22, rootMargin: '0px 0px -6% 0px' });

    document.querySelectorAll('.stats-chapter').forEach((ch) => chapterIo.observe(ch));
    if (location.hash) {
        const target = document.querySelector(location.hash);
        if (target) {
            requestAnimationFrame(() => {
                target.scrollIntoView({ behavior: reduce ? 'auto' : 'smooth', block: 'start' });
                activateChapter(target);
                setActiveDot(target.id);
            });
        }
    }
})();

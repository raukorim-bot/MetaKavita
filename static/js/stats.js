/**
 * Page /stats — récit en chapitres (count-up, dots, navigation fluide, Intersection Observer).
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
        const duration = 1000;
        const start = performance.now();
        function frame(now) {
            const t = Math.min(1, (now - start) / duration);
            const eased = 1 - Math.pow(1 - t, 3);
            const val = target * eased;
            el.textContent = (decimals ? val.toFixed(decimals) : String(Math.round(val))) + suffix;
            if (t < 1) requestAnimationFrame(frame);
            else el.textContent = (decimals ? target.toFixed(decimals) : String(Math.round(target))) + suffix;
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
        const duration = 1100;
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
        if (!id) return;
        document.querySelectorAll('.stats-dots a').forEach((a) => {
            a.classList.toggle('is-active', a.getAttribute('data-dot') === id);
        });
    }

    function scrollToChapter(target) {
        if (!target) return;
        const nav = document.querySelector('.stats-nav');
        const navH = nav ? nav.getBoundingClientRect().height : 0;
        const isHero = target.id === 'stats-hero';
        const top = target.getBoundingClientRect().top + (window.pageYOffset || document.documentElement.scrollTop) - (isHero ? 0 : navH);
        window.scrollTo({
            top: Math.max(0, top),
            behavior: reduce ? 'auto' : 'smooth',
        });
    }

    // Navigation au clic sur les points latéraux
    function initDotsNavigation() {
        document.querySelectorAll('.stats-dots a').forEach((dotLink) => {
            dotLink.addEventListener('click', (e) => {
                const targetId = dotLink.getAttribute('href');
                if (!targetId || !targetId.startsWith('#')) return;
                const target = document.querySelector(targetId);
                if (!target) return;
                e.preventDefault();
                scrollToChapter(target);
                setActiveDot(target.id);
                try {
                    history.replaceState(null, '', targetId);
                } catch (_) {}
            });
        });
    }

    // Invitation à défiler (scroll-hint) cliquable
    function initScrollHint() {
        const hint = document.querySelector('.scroll-hint');
        if (!hint) return;
        function proceed() {
            const chapters = Array.from(document.querySelectorAll('.stats-chapter'));
            const nextChapter = chapters.find((ch) => ch.id !== 'stats-hero') || chapters[1];
            if (nextChapter) {
                scrollToChapter(nextChapter);
                setActiveDot(nextChapter.id);
                try {
                    history.replaceState(null, '', '#' + nextChapter.id);
                } catch (_) {}
            }
        }
        hint.addEventListener('click', proceed);
        hint.addEventListener('keydown', (e) => {
            if (e.key === 'Enter' || e.key === ' ') {
                e.preventDefault();
                proceed();
            }
        });
    }

    // Navigation clavier fluide pour passer d'un chapitre à l'autre (PageDown / PageUp / J / K)
    function initKeyboardNavigation() {
        const chapters = Array.from(document.querySelectorAll('.stats-chapter'));
        if (!chapters.length) return;
        window.addEventListener('keydown', (e) => {
            const tag = (e.target && e.target.tagName) || '';
            if (tag === 'INPUT' || tag === 'TEXTAREA' || tag === 'SELECT' || e.altKey || e.ctrlKey || e.metaKey) return;
            if (e.key !== 'PageDown' && e.key !== 'PageUp' && e.key !== 'j' && e.key !== 'k') return;

            const focalY = window.innerHeight * 0.35;
            let currentIndex = chapters.findIndex((ch) => {
                const rect = ch.getBoundingClientRect();
                return rect.top <= focalY + 10 && rect.bottom >= focalY;
            });
            if (currentIndex < 0) currentIndex = 0;

            if (e.key === 'PageDown' || e.key === 'j') {
                if (currentIndex < chapters.length - 1) {
                    e.preventDefault();
                    const next = chapters[currentIndex + 1];
                    scrollToChapter(next);
                    setActiveDot(next.id);
                }
            } else if (e.key === 'PageUp' || e.key === 'k') {
                if (currentIndex > 0) {
                    e.preventDefault();
                    const prev = chapters[currentIndex - 1];
                    scrollToChapter(prev);
                    setActiveDot(prev.id);
                }
            }
        });
    }

    // Suivi précis du chapitre actif dans le viewport (gère les chapitres hauts et courts)
    const visibleChapters = new Map();
    const dotIo = new IntersectionObserver((entries) => {
        entries.forEach((entry) => {
            if (entry.isIntersecting) {
                visibleChapters.set(entry.target, entry);
            } else {
                visibleChapters.delete(entry.target);
            }
        });

        if (visibleChapters.size > 0) {
            let bestChapter = null;
            let minDistance = Infinity;
            const focalY = window.innerHeight * 0.35;

            visibleChapters.forEach((_, chapter) => {
                const rect = chapter.getBoundingClientRect();
                if (rect.top <= focalY && rect.bottom >= focalY) {
                    bestChapter = chapter;
                    minDistance = 0;
                } else if (minDistance !== 0) {
                    const dist = Math.min(Math.abs(rect.top - focalY), Math.abs(rect.bottom - focalY));
                    if (dist < minDistance) {
                        minDistance = dist;
                        bestChapter = chapter;
                    }
                }
            });

            if (bestChapter) {
                setActiveDot(bestChapter.id);
            }
        }
    }, {
        threshold: [0, 0.15, 0.4, 0.7],
        rootMargin: '0px 0px 0px 0px'
    });

    document.querySelectorAll('.stats-chapter').forEach((ch) => dotIo.observe(ch));

    if (reduce) {
        document.querySelectorAll('.stats-chapter').forEach(activateChapter);
    } else {
        const chapterIo = new IntersectionObserver((entries) => {
            entries.forEach((entry) => {
                if (!entry.isIntersecting) return;
                activateChapter(entry.target);
                chapterIo.unobserve(entry.target);
            });
        }, { threshold: 0.15, rootMargin: '0px 0px -4% 0px' });

        document.querySelectorAll('.stats-chapter').forEach((ch) => chapterIo.observe(ch));
    }

    initDotsNavigation();
    initScrollHint();
    initKeyboardNavigation();

    if (location.hash) {
        const target = document.querySelector(location.hash);
        if (target) {
            requestAnimationFrame(() => {
                scrollToChapter(target);
                activateChapter(target);
                setActiveDot(target.id);
            });
        }
    }
})();

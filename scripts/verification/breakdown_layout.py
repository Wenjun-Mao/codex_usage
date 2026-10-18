"""One transport snapshot preserving the breakdown's per-node invariants."""

ACCOUNT_DATE_CHECK = """(text, at) => {
    const line = text.split('\\n')[1] ?? '';
    const m = /^(Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec) (\\d{1,2}), (\\d{4}) at (\\d{2}):(\\d{2}) \\(UTC([+-])(\\d{2}):(\\d{2})(?::(\\d{2}))?\\)$/.exec(line);
    if (!m || !Number.isFinite(at)) return false;
    const month = ['Jan','Feb','Mar','Apr','May','Jun','Jul','Aug','Sep','Oct','Nov','Dec'].indexOf(m[1]);
    const [day,year,hour,minute] = m.slice(2,6).map(Number);
    if (hour>23 || minute>59 || +m[7]>23 || +m[8]>59 || +(m[9]??0)>59) return false;
    const clock = Date.UTC(year,month,day,hour,minute), date = new Date(clock);
    if (date.getUTCMonth()!==month || date.getUTCDate()!==day) return false;
    const offset = (+m[7]*3600 + +m[8]*60 + +(m[9]??0)) * (m[6]==='-' ? -1 : 1);
    const captured = (clock-offset*1000)/1000;
    return at>=captured && at<captured+60;
}"""

SNAPSHOT = """() => {
    const sections = [...document.querySelectorAll('.usage-breakdown')];
    if (sections.length !== 1) return {sections: sections.length};
    const e = sections[0], find = s => [...e.querySelectorAll(s)];
    const visible = x => {const r=x.getBoundingClientRect();
        return r.width>0 && r.height>0 && getComputedStyle(x).visibility==='visible';};
    const axes = find('.ub-axis').map(a => {
        const gutter=a.getBoundingClientRect(), right=gutter.right-parseFloat(getComputedStyle(a).paddingRight);
        return {visible:visible(a), font:getComputedStyle(a).fontSize,
            boxes:[...a.children].filter(s=>s.textContent.trim()).map(s=>{
                const range=document.createRange();range.selectNodeContents(s);
                const text=range.getBoundingClientRect(),span=s.getBoundingClientRect();
                return {label:s.textContent,textLeft:text.left,textRight:text.right,spanLeft:span.left,
                    spanRight:span.right,gutterLeft:gutter.left,gutterRight:right};})};});
    const timeAxes=find('.ub-time-axis').map(a=>{
        const rect=a.getBoundingClientRect(),start=+a.dataset.start,end=+a.dataset.end;
        const ticks=[...a.querySelectorAll('.ub-tick')].filter(t=>getComputedStyle(t).display!=='none');
        return {font:getComputedStyle(a).fontSize, rect:rect.toJSON(),
            ticks:ticks.map(t=>{const span=t.querySelector('span'),range=document.createRange();
                range.selectNodeContents(span);return {glyph:range.getBoundingClientRect().toJSON(),
                    span:span.getBoundingClientRect().toJSON(),
                    error:Math.abs(t.getBoundingClientRect().left-rect.left-(+t.dataset.at-start)/
                        Math.max(.000001,end-start)*a.clientWidth)};})};});
    const datedAccount = ACCOUNT_DATE_CHECK;
    const titles=find('svg rect,svg circle,svg path,svg .ub-tiny-segment').map(m=>({
        text:m.querySelector('title,desc')?.textContent??'',
        account:m.classList.contains('ub-account-point'),at:Number(m.dataset.at)}));
    const links=find('.ub-hover-target[href]').map(a=>({label:a.getAttribute('aria-label')??'',href:a.getAttribute('href')}));
    const text=e.innerText;
    return {sections:sections.length,scripts:document.querySelectorAll('script').length,
        sectionFits:e.scrollWidth<=e.clientWidth+1,axes,timeAxes,
        svg:find('svg').length,windowPickers:find('.ub-window-picker').length,
        rightAxes:find('.ub-right-axis').length,rightText:e.querySelector('.ub-right-axis')?.innerText.trim(),
        rightTicks:find('.ub-right-axis span').map(x=>x.textContent),
        legend:e.querySelector('.ub-meter-legend')?.innerText??'',
        titlesDated:titles.filter(t=>t.account ? datedAccount(t.text,t.at) : t.text.includes('2026-')).length,titleCount:titles.length,
        linksDated:links.filter(a=>a.label.includes('2026-')).length,linkCount:links.length,
        linksIssued:links.every(a=>a.href.startsWith('command:codexUsage.navigateBreakdown?')),
        finiteMissing:text.includes('No finite valid balances among in-domain captures'),
        capturesMissing:text.includes('No in-domain balance captures'),offset:text.includes('Axis offset:'),
        oldContext:text.includes('Full-range daily context'),
        diagnosticSections:find('details > summary').filter(s=>
            ['Scope and continuity evidence','Small segments','Account overlay evidence'].includes(s.textContent)).length,
        controlsFit:find('.ub-controls').every(g=>g.scrollWidth<=g.clientWidth+1)};
}""".replace('ACCOUNT_DATE_CHECK', ACCOUNT_DATE_CHECK)


def assert_layout(snapshot, label, state):
    assert snapshot["sections"] == 1, snapshot
    assert snapshot["scripts"] == 0
    assert snapshot["sectionFits"] and snapshot["controlsFit"], (label, snapshot)
    for axis in snapshot["axes"]:
        assert axis["visible"] and axis["font"] == "12px", (label, axis)
        assert all(b["textLeft"] >= max(b["spanLeft"], b["gutterLeft"])-1
            and b["textRight"] <= min(b["spanRight"], b["gutterRight"])+1
            for b in axis["boxes"]), (label, axis)
    assert snapshot["titlesDated"] == snapshot["titleCount"], label
    assert snapshot["linksDated"] == snapshot["linkCount"], label
    if snapshot["svg"]:
        assert snapshot["linkCount"] and snapshot["linksIssued"], label
    if label == "multi-weekly":
        assert "another-limit · weekly · plus" in snapshot["legend"]
        assert "codex · weekly · pro" in snapshot["legend"]
    if label in ("unknown-balances", "unlimited-balances"):
        assert snapshot["rightText"] == "Unknown"
        assert snapshot["finiteMissing"] and not snapshot["capturesMissing"]
    if label == "extreme-balances":
        assert snapshot["offset"] and len(set(snapshot["rightTicks"])) == 3
    if state["view"] == "time":
        assert len(snapshot["timeAxes"]) == 1 and snapshot["svg"] == 1
        assert len(snapshot["axes"]) == (1 if state["overlay"] == "none" else 2)
        assert snapshot["windowPickers"] == 1
    else:
        assert len(snapshot["timeAxes"]) == 0 and snapshot["rightAxes"] == 0
    assert not snapshot["oldContext"]
    assert snapshot["diagnosticSections"] == 0, label
    for axis in snapshot["timeAxes"]:
        assert axis["font"] == "12px"
        for field in ("glyph", "span"):
            boxes = [tick[field] for tick in axis["ticks"]]
            assert all(b["left"] >= axis["rect"]["left"]-1
                and b["right"] <= axis["rect"]["right"]+1
                and (not i or boxes[i-1]["right"] <= b["left"]+1)
                for i, b in enumerate(boxes)), (label, field, axis)
        assert all(tick["error"] < 2 for tick in axis["ticks"]), (label, axis)

// REQUEST is supplied by the Python bridge. Never save or edit source artwork.
try {
    const {Document, FileExportOptions, FileExportArea} = require('/document.js');
    const {Selection} = require('/selections.js');
    const {ParagraphAlignXType} = require('/paragraphatts.js');
    const d = Document.all.find(doc => doc.path === REQUEST.path);
    if (!d) throw Error('Requested document is not open');
    if (d.isDirty) throw Error('Requested document has unsaved changes; save it before exporting');
    if (REQUEST.session && d.sessionUuid !== REQUEST.session) throw Error('Document session changed');
    function box(b) { return [b.x, b.y, b.width, b.height]; }
    function colour(fill) {
        if (fill.constructor.name !== 'SolidFill') return null;
        const c = fill.colour.rgba8;
        return {color: '#' + [c.r,c.g,c.b].map(v=>v.toString(16).padStart(2,'0')).join(''), alpha: c.alpha / 255 * fill.alpha};
    }
    function walk(n, indices) {
        const result = {
            name: n.userDescription, kind: n.constructor.name, indices,
            box: box(n.spreadBaseBox), visibleBox: box(n.getSpreadVisibleBox(false)),
            visible: n.visibilityInterface.isVisible,
            opacity: n.visibilityInterface.globalOpacity,
            effects: n.layerEffectsInterface?.hasActiveEffects || false,
            enclosures: Array.from(n.enclosures).length,
            transform: Array.from(n.baseToSpreadTransform.data),
            children: Array.from(n.children, (child, i)=>walk(child, indices.concat(i)))
        };
        if (n.isTextNode) {
            const begin = n.storyRange.begin;
            const g = n.story.getGlyphAtts(begin);
            const align = n.story.getParagraphAtts(begin).alignXType.value;
            result.paragraphAlign = align;
            result.text = n.storyInterface.text;
            result.font = g.font.postscriptName;
            result.fontSize = g.height;
            result.fill = colour(g.brushFill.fill);
            result.align = align === ParagraphAlignXType.Centre.value ? 'center' : align === ParagraphAlignXType.Right.value ? 'right' : 'left';
            result.runs = Array.from(n.story.glyphAttRuns, run => ({
                begin: run.begin, end: run.end, font: run.glyphAtts.font.postscriptName,
                fontSize: run.glyphAtts.height, fill: colour(run.glyphAtts.brushFill.fill)
            }));
        }
        return result;
    }
    let result;
    if (REQUEST.action === 'inspect') {
        result = {path: d.path, session: d.sessionUuid, dpi: d.dpi, tree: walk(d.rootNode, [])};
    } else if (REQUEST.action === 'render') {
        // Affinity's selection export uses the live document selection. Merely
        // passing a detached Selection to FileExportArea exports the wrong art.
        if (Document.current.path !== d.path) throw Error('Activate the requested document before exporting');
        const originalSelection = d.selection;
        result = [];
        try {
            for (const job of REQUEST.jobs) {
                let n = d.rootNode;
                for (const index of job.indices) n = Array.from(n.children)[index];
                if (!n || n.userDescription !== job.name) throw Error('Layer changed during export: ' + job.name);
                d.selection = Selection.create(d, n);
                d.export(job.output, FileExportOptions.createWithPresetName('PNG'), FileExportArea.createForSelection(d.selection));
                result.push({output: job.output, box: box(n.getSpreadVisibleBox(false))});
            }
        } finally {
            d.selection = originalSelection;
        }
    } else throw Error('Unknown action');
    if (d.isDirty) throw Error('Document changed during export');
    console.log('__AFFINITY2UI__' + JSON.stringify({ok:true, result}));
} catch (error) {
    console.log('__AFFINITY2UI__' + JSON.stringify({ok:false, error:String(error)}));
}

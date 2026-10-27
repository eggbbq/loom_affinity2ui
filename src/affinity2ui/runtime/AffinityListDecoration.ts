/** 保留列表装饰节点，同时让原生列表排版只计算 item 单元格。 */
@Laya.runInEditor
@Laya.regClass()
export class AffinityListDecoration extends Laya.Script {
    runInEditor = true;

    @Laya.property({ type: Number })
    sourceX = 0;

    @Laya.property({ type: Number })
    sourceY = 0;
    onAwake(): void {
        this.owner._setBit(Laya.NodeFlags.ESCAPE_LAYOUT, true);
        // Editor layout may have run before component awakening. Restore the
        // design position as well as excluding this node from future layout.
        (this.owner as Laya.Sprite).pos(this.sourceX, this.sourceY);
        let list = this.owner.parent;
        while (list && !(list instanceof Laya.GList)) {
            list = list.parent;
        }
        if (list instanceof Laya.GList) {
            list.layout.refresh(true);
        }
    }
}

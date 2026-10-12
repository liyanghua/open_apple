# s06 动态插片提示词草案（未执行）

本文件只作为分镜审核的一部分。视频模型参数、干净参考图和本轮费用须确认后才能执行。不是生成结果，也不是产品检测证明。

## 连续性与参考

- 产品：同款无印字透明柔性桌垫，透出木纹；不杜撰厚度数字、包装或型号。
- 场景：独立浅木桌近景，与原片以明确硬切分场景，不要求同一张桌子；单镜内桌色、木纹、桌垫与油渍位置保持连续。
- 人物：只出现一只成人手和白布，无人脸、儿童或身份绑定。
- 图03原件只作人工动作/信息参考，带字卡和抽检Logo，不直接送模。建议经批准后裁掉上方文字区，保留油渍、白布与商品上下文；衍生图需记录父哈希和自身哈希。上下文不足时停止，不杜撰透明垫外观。
- 9:16，720p，候选4秒，最终使用完整动作区间约3.2秒；无模型原生音频，统一使用豆包配音。

## 中文

真实商业产品拍摄质感，固定俯斜近景。浅木色桌面上铺着无印字、透明柔软的桌垫，木纹透过桌垫可见，桌垫保持平整贴合。垫面上预先存在一小片自然橙色油渍，旁边是一只成人手握着白色棉布；这不是倾倒镜头。开头短暂停留，让油渍与干净边界可见。手将白布接触到油渍边缘，然后保持接触、施加轻微压力，沿一个方向连续擦过，布后留下自然干净的区域，最后停留展示结果。全程一个镜头，固定光线、桌色、木纹、垫边、手部和污渍位置。保持真实反光和摩擦，不让液体凭空消失或穿过桌垫。画面不含任何字幕、Logo、证书、数字、品牌或检测结论。不要生成声音。

## English

Realistic commercial product footage in a fixed oblique overhead close-up. An unprinted, clear, flexible table protector lies flat and flush on a light wood table, with the wood grain visible through it. A small natural orange oil stain is already on the protector, next to an adult hand holding a white cotton cloth; this is not a pouring shot. Begin with a brief still hold so the stain and the clean boundary are visible. The hand brings the cloth into visible contact with the edge of the stain, maintains contact and light pressure, and wipes continuously in one direction, leaving a naturally clean trail behind the cloth. End with a short hold on the result. Use one continuous take with fixed light, table color, grain, protector edge, hand, and stain position. Preserve realistic reflections and friction; the liquid must not disappear spontaneously or pass through the protector. No captions, logos, certificates, numbers, brands, or testing claims anywhere in the image. Do not generate audio.

## 禁止 / Negative constraints

中文：隐藏切换、预先擦净、触碰前污渍消失、液体瞬移或倒流、波纹改色、桌体漂移、桌垫翘边或变形、额外手指、手穿桌面、硬玻璃替代软桌垫、塑料假皮肤、卡通、CGI、过度磨皮、文字、Logo、检测编号、假证书。

English: hidden cuts, a pre-cleaned surface, a stain disappearing before contact, teleporting or reversed liquid, recoloring ripples, drifting table geometry, lifted or warped protector edges, extra fingers, a hand intersecting the table, rigid glass replacing the flexible protector, plastic skin, cartoon, CGI, excessive beauty retouching, text, logos, test numbers, fabricated certificates.

## 验收

必须看到接触→连续擦拭→结果，完整链条能装入3.2秒才可采用；不能通过裁掉接触点来勉强装进时槽。此镜不含液体倾倒或碰撞，不套用额外倾倒预检调用。画面只作效果示意，不证明“960小时”性能；后期单独加AI示意标签与已批准口播字幕。

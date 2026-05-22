# 维度5差异清单汇总

- 全量标准记录：71
- PDF题块抽取：校内 25/25，思维 17/17，分班考 27/27
- 知识点需复核：13
- 漏判/未稳定判定：44
- 来源不一致：11
- 知识点近似/可接受：3

> 说明：本次对比基于 PDF 文本抽取 + 当前 Dim5KnowledgeGraphMatcher。含图形、公式缺失的题目会偏保守，差异题仍需结合原图复核。

## 需要优先复核的问题题目

| 试卷 | 题号 | 差异 | Excel标准知识点 | 系统结果 | 备注 |
|---|---:|---|---|---|---|
| 学情诊断卷-校内 | 1 | 知识点需复核 | 基准数非0,用正、负数表示生活中的量 | 校内三年级：平均分应用 |  |
| 学情诊断卷-校内 | 2 | 漏判/未稳定判定 | 判断组成三角形的三条线长度 | broad_category_only | weak_structure_evidence_only |
| 学情诊断卷-校内 | 3 | 漏判/未稳定判定 | 小数、分数、百分数的比较大小 | ambiguous | ambiguous_confirmed_candidates |
| 学情诊断卷-校内 | 4 | 漏判/未稳定判定 | 常见百分率的实际应用 | broad_category_only | weak_structure_evidence_only |
| 学情诊断卷-校内 | 5 | 漏判/未稳定判定 | 与比相关的综合题 | review_required | no_confirmed_candidate |
| 学情诊断卷-校内 | 6 | 漏判/未稳定判定 | 用字母表示图形规律 | review_required | no_confirmed_candidate |
| 学情诊断卷-校内 | 7 | 漏判/未稳定判定 | 物体完全浸没,无水溢出,求水上升高度 | broad_category_only | weak_structure_evidence_only |
| 学情诊断卷-校内 | 8 | 漏判/未稳定判定 | 具体数值未知,根据一个数量的两次增减变化,求变化幅度 | ambiguous | ambiguous_confirmed_candidates |
| 学情诊断卷-校内 | 9 | 漏判/未稳定判定 | 已知比一个数多(少)的分率,求单位“1” | review_required | no_confirmed_candidate |
| 学情诊断卷-校内 | 10 | 来源不一致 | 复杂图形的旋转体体积 | 奥数六年级：比例解应用题 | 标准来源=校内，系统来源=奥数 |
| 学情诊断卷-校内 | 11 | 来源不一致 | 三角形和平行四边形的关系 | 奥数知识：勾股面积关系 | 标准来源=校内，系统来源=奥数 |
| 学情诊断卷-校内 | 12 | 漏判/未稳定判定 | 游戏规则的公平性判断 | ambiguous | ambiguous_confirmed_candidates |
| 学情诊断卷-校内 | 13 | 漏判/未稳定判定 | 与分数乘法结合,求出和后再按比分配 | review_required | no_confirmed_candidate |
| 学情诊断卷-校内 | 14 | 漏判/未稳定判定 | 结合实际,确定计算哪些面的面积再计算 | ambiguous | ambiguous_confirmed_candidates |
| 学情诊断卷-校内 | 15 | 来源不一致 | 写出(组成)符合题目条件的是2、3、5的倍数的数 | 奥数五年级：约数与倍数 | 标准来源=校内，系统来源=奥数 |
| 学情诊断卷-校内 | 16 | 漏判/未稳定判定 | 分数乘法综合题-进阶 | broad_category_only | weak_structure_evidence_only |
| 学情诊断卷-校内 | 17 | 来源不一致 | 组合图形的体积计算 | 奥数知识：圆柱卷纸侧面展开与层数 | 标准来源=校内，系统来源=奥数 |
| 学情诊断卷-校内 | 18 | 知识点需复核 | 已知长方形的长,求圆的面积 | 校内三年级：除法估算 |  |
| 学情诊断卷-校内 | 19 | 漏判/未稳定判定 | 异分母分数加减 利用分数乘分数的算法进行计算 利用分数乘小数的算法进行计算 不带括号的分数加减乘混合运算 小数和分数加、减法 小数部分位数相同的退位减法 带括号的分数加减乘混合运算 分数四则混合运算,不带括号 | review_required | no_confirmed_candidate |
| 学情诊断卷-校内 | 20 | 漏判/未稳定判定 | 1、分数四则混合运算,带括号,直接计算 2、分小四则混合运算 3、找出隐藏的数,再提取公因数 | ambiguous | ambiguous_confirmed_candidates |
| 学情诊断卷-校内 | 21 | 来源不一致 | 1、多步计算的分数方程; 2、依据比例的基本性质解比例; 3、解稍复杂的含分、小、百的方程 | 奥数六年级：方程解应用题 | 标准来源=校内，系统来源=奥数 |
| 学情诊断卷-校内 | 22 | 漏判/未稳定判定 | 1、圆的周长的简单应用 2、根据圆的半径或直径,求圆的面积 3、半径隐藏的环形面积计算 | broad_category_only | weak_structure_evidence_only |
| 学情诊断卷-校内 | 23 | 知识点需复核 | 说理类-长、正方体体积和容积相关 | 校内一年级：认识立体图形 |  |
| 学情诊断卷-校内 | 24 | 漏判/未稳定判定 | 1、分割法求组合图形面积 2、直观利用“整体-部分”求不规则图形面积 3-4、不规则图形的周长和面积计算练习 | ambiguous | ambiguous_confirmed_candidates |
| 学情诊断卷-校内 | 25 | 漏判/未稳定判定 | 运用扇形统计图解决问题 | ambiguous | ambiguous_confirmed_candidates |
| 学情诊断卷-思维 | 1 | 知识点需复核 | 两个量的除法复合比 | 奥数六年级：比例解应用题 |  |
| 学情诊断卷-思维 | 2 | 漏判/未稳定判定 | 大小正方形间的沙漏 | broad_category_only | weak_structure_evidence_only |
| 学情诊断卷-思维 | 3 | 漏判/未稳定判定 | 多位数乘多位数,位数分析问题 | ambiguous | ambiguous_confirmed_candidates |
| 学情诊断卷-思维 | 4 | 漏判/未稳定判定 | 工作量相同的来回帮忙问题 | broad_category_only | weak_structure_evidence_only |
| 学情诊断卷-思维 | 5 | 漏判/未稳定判定 | 不完全浸没水未溢出 | ambiguous | ambiguous_confirmed_candidates |
| 学情诊断卷-思维 | 6 | 漏判/未稳定判定 | 连续三级的爬楼梯问题 | review_required | no_confirmed_candidate |
| 学情诊断卷-思维 | 7 | 来源不一致 | 条件判断型的普通规则新运算 | 校内五年级：等量代换与简易方程 | 标准来源=奥数，系统来源=校内 |
| 学情诊断卷-思维 | 9 | 漏判/未稳定判定 | 根据平方差连续约分 | review_required | no_confirmed_candidate |
| 学情诊断卷-思维 | 10 | 漏判/未稳定判定 | 叠数的简单计算 | review_required | no_confirmed_candidate |
| 学情诊断卷-思维 | 11 | 漏判/未稳定判定 | 鱼头鱼尾换元法 | review_required | no_confirmed_candidate |
| 学情诊断卷-思维 | 12 | 漏判/未稳定判定 | 连分数方程 | review_required | no_confirmed_candidate |
| 学情诊断卷-思维 | 13 | 知识点需复核 | 速度和时间成反比解行程-原 | 奥数六年级：比例解应用题 |  |
| 学情诊断卷-思维 | 14 | 漏判/未稳定判定 | 连辅助线后构造梯形模型 | broad_category_only | weak_structure_evidence_only |
| 学情诊断卷-思维 | 15 | 知识点需复核 | 草生长,生长速度未知,求牛数 | 奥数五年级：牛吃草问题与钟表问题 |  |
| 学情诊断卷-思维 | 16 | 知识点需复核 | 简单的列表分析 | 奥数六年级：比例解应用题 |  |
| 学情诊断卷-思维 | 17 | 知识点需复核 | 基础题模——整数型等比数列求和 真题模拟——十一学校 | 奥数知识：勾股面积关系 |  |
| 分班考模拟卷 | 1 | 漏判/未稳定判定 | 夹在两条平行线之间的平四、三角、梯形面积比较 | ambiguous | ambiguous_confirmed_candidates |
| 分班考模拟卷 | 2 | 知识点需复核 | 按时间分段,先求独做工作量 | 奥数五年级：工程问题 |  |
| 分班考模拟卷 | 3 | 漏判/未稳定判定 | 简单的正反比计算,两个对象 | ambiguous | ambiguous_confirmed_candidates |
| 分班考模拟卷 | 4 | 知识点需复核 | 从面倍到底倍 | 奥数三年级：长度与角度的计算 |  |
| 分班考模拟卷 | 5 | 来源不一致 | 用字母表示图形规律 | 奥数四年级：排列组合 | 标准来源=校内，系统来源=奥数 |
| 分班考模拟卷 | 6 | 来源不一致 | 小数、百分数比较大小 | 奥数四年级：排列组合 | 标准来源=校内，系统来源=奥数 |
| 分班考模拟卷 | 9 | 漏判/未稳定判定 | 树形图排队问题 | review_required | no_confirmed_candidate |
| 分班考模拟卷 | 10 | 来源不一致 | 长方体染色,根据长宽高求涂色方块数 | 校内一年级：认识立体图形 | 标准来源=奥数，系统来源=校内 |
| 分班考模拟卷 | 11 | 漏判/未稳定判定 | 根据顺速和逆速求船速和水速 | broad_category_only | weak_structure_evidence_only |
| 分班考模拟卷 | 12 | 漏判/未稳定判定 | 三个条件的逐级满足 | ambiguous | ambiguous_confirmed_candidates |
| 分班考模拟卷 | 13 | 漏判/未稳定判定 | 排列组合辨析 | broad_category_only | weak_structure_evidence_only |
| 分班考模拟卷 | 14 | 来源不一致 | 切片法求体积(不同图形) | 校内一年级：认识立体图形 | 标准来源=奥数，系统来源=校内 |
| 分班考模拟卷 | 15 | 漏判/未稳定判定 | 复杂取整取小 | review_required | no_confirmed_candidate |
| 分班考模拟卷 | 16 | 知识点需复核 | 分解结果求算式未知数 | 奥数五年级：整除 |  |
| 分班考模拟卷 | 17（1） | 漏判/未稳定判定 | 小数中加减法分拆构造公因数 | review_required | no_confirmed_candidate |
| 分班考模拟卷 | 17（2） | 漏判/未稳定判定 | 含百分数四则混合运算 | review_required | no_confirmed_candidate |
| 分班考模拟卷 | 18 | 漏判/未稳定判定 | 算式提公因数的形式后整体约分 | review_required | no_confirmed_candidate |
| 分班考模拟卷 | 19 | 漏判/未稳定判定 | 分母拆成两项乘积后裂和 | review_required | no_confirmed_candidate |
| 分班考模拟卷 | 20 | 漏判/未稳定判定 | 根据平方差连续约分 | review_required | no_confirmed_candidate |
| 分班考模拟卷 | 21（1） | 漏判/未稳定判定 | 复杂重叠(多块阴影,整体计算) | broad_category_only | weak_structure_evidence_only |
| 分班考模拟卷 | 21（2） | 漏判/未稳定判定 | 用割补法求解复杂的面积 | broad_category_only | weak_structure_evidence_only |
| 分班考模拟卷 | 22 | 漏判/未稳定判定 | 利用“b+c=2×a”填出的三阶幻方 | broad_category_only | weak_structure_evidence_only |
| 分班考模拟卷 | 23 | 漏判/未稳定判定 | 相遇过程中的隐藏路程差 | ambiguous | ambiguous_confirmed_candidates |
| 分班考模拟卷 | 24 | 来源不一致 | 圆柱与圆锥综合题-基础 | 奥数六年级：立体几何 | 标准来源=校内，系统来源=奥数 |
| 分班考模拟卷 | 25 | 漏判/未稳定判定 | 草生长,生长速度未知,求天数 | broad_category_only | weak_structure_evidence_only |
| 分班考模拟卷 | 26 | 知识点需复核 | 十字交叉法反求混合前的两个重量 | 奥数知识：浓度问题 |  |
| 分班考模拟卷 | 27 | 知识点需复核 | 规律探究 | 奥数三年级：找规律 |  |
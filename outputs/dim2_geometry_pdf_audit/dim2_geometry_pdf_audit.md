# dim2 几何 PDF 自查报告

## 方法说明
- 本轮只处理用户指定的 3 个 PDF，不修改生产逻辑。
- PDF 用 PyMuPDF 抽取文字，并渲染页面图片做人工审计辅助；题目没有调用外部多模态 LLM。
- 表中的 actual 字段来自当前 `build_dim2_text_geometry_fallback_facts`、`build_dim2_visual_fallback_facts`、`evaluate_dim2_applicability` 和 `Dim2SpatialScorer`。
- 因为没有运行线上题块多模态模型，结论重点反映“上游模型事实缺失或不稳定时”的 dim2 退化风险，尤其是宽泛 `composite_area_model` 截胡。

## 总览
- PDF 数：3
- 总题数：82
- 几何候选题数：81
- dim2 实际计入题数：61
- 各 PDF 题数：{'立体图形.pdf': 26, '小升初几何模型.pdf': 26, '小升初平面几何.pdf': 30}
- 状态分布：{'suspicious': 32, 'needs_manual_review': 6, 'wrong': 40, 'correct': 4}
- Issue 分布：{'display_inaccurate': 32, 'ocr_or_visual_missing': 6, 'dim2_false_negative': 19, 'model_overridden_by_broad_label': 21, 'none': 4}

## 重点模型识别结果
| model | total | correct | suspicious | wrong | needs_manual_review |
| --- | --- | --- | --- | --- | --- |
| 一半模型 | 10 | 0 | 0 | 10 | 0 |
| 等积变形 | 10 | 0 | 0 | 10 | 0 |
| 蝴蝶模型 | 3 | 0 | 0 | 3 | 0 |
| 燕尾模型 | 3 | 0 | 0 | 3 | 0 |
| 相似模型 | 2 | 0 | 0 | 2 | 0 |

## 正确样例
| file | page | question_no | expected_geometry_model | actual_geometry_model_labels | dim2_level | status |
| --- | --- | --- | --- | --- | --- | --- |
| 小升初平面几何.pdf | 4 | 9 | 基本面积公式、圆与扇形公式 | 圆与扇形公式 | L2 | correct |
| 小升初平面几何.pdf | 9 | 19 | 圆与扇形公式、组合图形面积 | 圆与扇形割补、组合图形面积 | L3 | correct |
| 小升初平面几何.pdf | 11 | 22 | uncertain_non_geometry_board_coordinate | uncertain |  | correct |
| 小升初平面几何.pdf | 14 | 28 | uncertain_non_geometry_board_coordinate | uncertain |  | correct |

## 可疑/错误样例
| file | page | question_no | question_text | expected_geometry_model | actual_geometry_model_labels | dim2_level | status | issue_type | suggested_fix |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 立体图形.pdf | 1 | 1 | 下图中的1、2是两块形状不同的铁皮,将每块铁皮弯折后焊接成一个无盖的长方体铁桶(2号焊接成的是一个 底面为正方形的无盖长方体),比较两种铁皮焊接成铁桶后的装水情况( ). A、1号... | 展开图剪拼、立体图形公式 | 水位体积、立体图形公式 | L5 | suspicious | display_inaccurate | 题目不是单纯直接公式题；若仅按基础公式展示，会误呈现结构负担。 |
| 立体图形.pdf | 2 | 3 | 修建一个圆柱形的沼气池,底面直径8米,深度是底面直径的 ,在池内的四壁和下底抹上水泥,抹水泥部分的面 积是多少平方米? | 立体图形公式 | uncertain |  | wrong | dim2_false_negative | 几何题未进入 dim2，应补充几何候选门禁或提升题块图像证据稳定性。 |
| 立体图形.pdf | 2 | 4 | 爸爸送给乐乐一个圆锥形的玩具(如图).这个玩具的体积是多少立方厘米?如果用一个长方体纸盒包装它,制作 纸盒至少需要多少平方厘米的纸板?(接口处忽略不计,π取3.14). | 立体图形公式 | 组合图形面积 | L3 | suspicious | display_inaccurate | 当前只落到宽泛组合图形面积；需要人工确认是否有更具体的割补、比例、圆扇形或立体模型。 |
| 立体图形.pdf | 3 | 5 | 一个圆柱体的容器的底部放着一块正方体铅块,现在打开水⻰头向容器内注水(匀速注入)。15秒钟时水恰好没过 铅块的上表面,又过了1分半钟,水恰好注满了容器。若容器的高度是24厘米,铅块... | 水位体积、立体图形公式 | uncertain |  | wrong | dim2_false_negative | 几何题未进入 dim2，应补充几何候选门禁或提升题块图像证据稳定性。 |
| 立体图形.pdf | 3 | 6 | 圆柱和圆锥的体积之比是2:1,其中底面半径之比是2:3,则高之比是 . | 立体图形公式、面积比例关系 | uncertain |  | wrong | dim2_false_negative | 几何题未进入 dim2，应补充几何候选门禁或提升题块图像证据稳定性。 |
| 立体图形.pdf | 3 | 7 | 一根长方体木料,正好可以锯成两个同样的正方体,这时表面积增加了24平方厘米,这根长方体木料的表面积是 平方厘米. | 立体切拼、立体图形公式 | 立体图形公式 | L2 | suspicious | display_inaccurate | 实际输出只命中泛化公式/组合图形，缺少更具体的几何子类型展示。 |
| 立体图形.pdf | 4 | 8 | 一个圆锥的底面周长是25.12厘米,高是4厘米.从圆锥的顶点沿着高将它切成两半,表面积之和比原圆锥的表面 积增加了 平方分米. | 立体切拼、立体图形公式 | 立体图形公式 | L2 | suspicious | display_inaccurate | 实际输出只命中泛化公式/组合图形，缺少更具体的几何子类型展示。 |
| 立体图形.pdf | 4 | 9 | 大圆柱的高是小圆柱的2倍,大圆柱的侧面积是小圆柱侧面积的12倍,大圆柱的体积是小圆柱体积的 倍. | 立体图形公式、面积比例关系 | 立体图形公式 | L2 | suspicious | display_inaccurate | 实际输出只命中泛化公式/组合图形，缺少更具体的几何子类型展示。 |
| 立体图形.pdf | 4 | 10 | 将一个正方体涂成红色,再每面等距离切若干刀,得到若干个同样大小的小正方体.若在这些小正方体中,一面 涂有红色的共有294个,则两面涂有红色和三面涂有红色的总共有 个. | 几何计数、立体图形公式 | uncertain |  | wrong | dim2_false_negative | 几何题未进入 dim2，应补充几何候选门禁或提升题块图像证据稳定性。 |
| 立体图形.pdf | 5 | 11 | (2024GA)将若干个体积相同的小正方体木块拼成一个大正方体,然后将大正方体的表面涂满红色.若将其拆开 后,只有一面涂成红色的小正方体木块的个数恰好是只有两面涂成红色的小正方体木... | 几何计数、立体图形公式 | uncertain |  | wrong | dim2_false_negative | 几何题未进入 dim2，应补充几何候选门禁或提升题块图像证据稳定性。 |
| 立体图形.pdf | 5 | 12 | (2022 GDFZ)把长,宽,高分别为8厘米,7厘米,5厘米的长方体表面涂色,然后切成棱长为1厘米的小正方体, 三面涂色的小正方体比两面涂色的小正方体少 (填分数). | 几何计数、立体图形公式 | uncertain |  | wrong | dim2_false_negative | 几何题未进入 dim2，应补充几何候选门禁或提升题块图像证据稳定性。 |
| 立体图形.pdf | 6 | 14 | (2024 GDFZ)有一圆柱形油罐底面的周长为12厘米,高为9厘米,一只老鼠从距底面1厘米的A处,爬行到对角的B 处吃⻝物,它爬行的最短路线为多少厘米? | 展开图剪拼、立体图形公式 | uncertain |  | wrong | dim2_false_negative | 几何题未进入 dim2，应补充几何候选门禁或提升题块图像证据稳定性。 |
| 立体图形.pdf | 7 | 15 | (2024 BYSS)一个底面半径是6厘米的圆柱形玻璃器皿里装有一部分水,水中漫没着一个高9厘米的圆锥体铅锤. 当铅锤从水中取出后,水面下降了0.5厘米,这个圆锥体的底面积是多少平... | 水位体积、立体图形公式 | 立体图形公式 | L2 | suspicious | display_inaccurate | 实际输出只命中泛化公式/组合图形，缺少更具体的几何子类型展示。 |
| 立体图形.pdf | 7 | 16 | (2024 ZCGF)将若干个棱长为a 的小立方块摆成如图所示的几何体. (1)求该几何体的表面积. (2)依图中摆放方法类似,如果几何体摆放了24层,求该几何体的表面积. | 三视图与表面积、立体切拼 | 组合图形面积 | L3 | suspicious | display_inaccurate | 实际输出只命中泛化公式/组合图形，缺少更具体的几何子类型展示。 |
| 立体图形.pdf | 8 | 17 | (2024 HPJX)一块底面半径6cm,高12cm的圆锥形钢材,把它熔铸成一根横截面半径是1cm的圆柱形钢条,这根 钢条长多少厘米? | 立体图形公式 | uncertain |  | wrong | dim2_false_negative | 几何题未进入 dim2，应补充几何候选门禁或提升题块图像证据稳定性。 |
| 立体图形.pdf | 9 | 20 | 下面是一个正方体和它的展开图,四边APQC是正方体的一个截面,请把截面的四条线段AC、CQ、QP、PA画在展 开图相应的位置上. | 展开图剪拼、立体切拼 | uncertain |  | wrong | dim2_false_negative | 几何题未进入 dim2，应补充几何候选门禁或提升题块图像证据稳定性。 |
| 立体图形.pdf | 11 | 23 | 一个密封的长方体水箱,从里面量长60厘米,宽30厘米,高30厘米.当水箱如下左图放置时,水深为20厘米,当 水箱如下右图放置时,水深 厘米. | 水位体积、立体图形公式 | uncertain |  | wrong | dim2_false_negative | 几何题未进入 dim2，应补充几何候选门禁或提升题块图像证据稳定性。 |
| 立体图形.pdf | 11 | 24 | 如图,转动长方形ABCD,生成两个不同的圆柱,图(1)的底面半径等于 cm,图(2)的体积等于 .(π取3) | 滚动与旋转、立体图形公式 | 组合图形面积 | L3 | suspicious | display_inaccurate | 实际输出只命中泛化公式/组合图形，缺少更具体的几何子类型展示。 |
| 立体图形.pdf | 11 | 25 | 一个圆柱体和一个圆锥体,底面半径之比为1:2,高之比为2:3,它们的体积比为 . | 立体图形公式、面积比例关系 | uncertain |  | wrong | dim2_false_negative | 几何题未进入 dim2，应补充几何候选门禁或提升题块图像证据稳定性。 |
| 立体图形.pdf | 12 | 26 | 四个同样大小的圆柱拼成一个高为40厘米的大圆柱时,表面积减少了72平方厘米,原来小圆柱的体积是 立方厘米. | 立体切拼、立体图形公式 | 立体图形公式 | L2 | suspicious | display_inaccurate | 实际输出只命中泛化公式/组合图形，缺少更具体的几何子类型展示。 |
| 小升初几何模型.pdf | 1 | 1 | 如图,长方形AFEB和长方形FDCE拼成了长方形ABCD,长方形ABCD的长是20,宽是12,则它内部阴影部分的面 积是 . | 割补法、组合图形面积 | 组合图形面积 | L3 | suspicious | display_inaccurate | 实际输出只命中泛化公式/组合图形，缺少更具体的几何子类型展示。 |
| 小升初几何模型.pdf | 1 | 2 | 如图,在梯形ABCD中,BC=2AD,E、F分别为BC、AB的中点。连接EF、FC。 若三角形EFC的面积为a,则梯形ABCD的面积是 。 | 一半模型、等高面积关系 | 组合图形面积 | L3 | wrong | model_overridden_by_broad_label | 具体几何模型应作为 primary；composite_area_model 只应作为 supporting/background。 |
| 小升初几何模型.pdf | 2 | 3 | (2023 ZCGF)如图,阴影部分的面积是 . | 圆与扇形割补、割补法 | 组合图形面积 | L3 | suspicious | display_inaccurate | 实际输出只命中泛化公式/组合图形，缺少更具体的几何子类型展示。 |
| 小升初几何模型.pdf | 2 | 4 | 已知正方形ABCD面积为1,E、F、G分别是BC、DC 和AD边的中点,求阴影部分的面积是多少? | 一半模型、等积变形 | 组合图形面积 | L3 | wrong | model_overridden_by_broad_label | 具体几何模型应作为 primary；composite_area_model 只应作为 supporting/background。 |
| 小升初几何模型.pdf | 3 | 5 | 如图所示,A、B、C、D是边长为10的正八边形的对角线交点,那么四边形 ABCD 的面积为 . | 割补法、几何计数 | 组合图形面积 | L3 | suspicious | display_inaccurate | 实际输出只命中泛化公式/组合图形，缺少更具体的几何子类型展示。 |
| 小升初几何模型.pdf | 3 | 6 | (2023 JGF)如图,三角形ABC中, ,三角形COD的面积是4,三角形COE的面积是3,则三角形ABC的 面积是多少? | 面积比例关系 | 组合图形面积 | L3 | suspicious | display_inaccurate | 实际输出只命中泛化公式/组合图形，缺少更具体的几何子类型展示。 |
| 小升初几何模型.pdf | 4 | 7 | (2024 ZCGF)如图,长方形被分成了若干块,其中三块的面积标注在图上,阴影部分的面积是多少?(单位:平 方厘米) | 面积比例关系、组合图形面积 | 组合图形面积 | L3 | suspicious | display_inaccurate | 实际输出只命中泛化公式/组合图形，缺少更具体的几何子类型展示。 |
| 小升初几何模型.pdf | 4 | 8 | 如图,求如图中阴影部分的面积(精确到0.01, 取3.14). | 圆与扇形割补 | 组合图形面积 | L3 | suspicious | display_inaccurate | 实际输出只命中泛化公式/组合图形，缺少更具体的几何子类型展示。 |
| 小升初几何模型.pdf | 5 | 9 | 三角形ABC 中, 是直角,已知 厘米, 厘米, 厘米, ,那么三角形 AMN (阴影部分)的面积是 平方厘米. | 一半模型、面积比例关系 | 组合图形面积 | L3 | wrong | model_overridden_by_broad_label | 具体几何模型应作为 primary；composite_area_model 只应作为 supporting/background。 |
| 小升初几何模型.pdf | 5 | 10 | 如图所示,S 阴= cm2. | 等积变形、一半模型 | uncertain |  | wrong | dim2_false_negative | 几何题未进入 dim2，应补充几何候选门禁或提升题块图像证据稳定性。 |

## 需要人工复核样例
| file | page | question_no | question_text | expected_geometry_model | actual_geometry_model_labels | issue_type | suggested_fix |
| --- | --- | --- | --- | --- | --- | --- | --- |
| 立体图形.pdf | 1 | 2 | 如下图,将长方形绕轴旋转一周,得到的立体图形是 ,它的体积是 立方厘米. | 滚动与旋转、立体图形公式 | 三视图与表面积 | ocr_or_visual_missing | 题目强依赖图形，当前审计未运行多模态题块识别，需用题块图片复核。 |
| 立体图形.pdf | 6 | 13 | (2024 THSS)如图,在一个正方体的两对侧面的中心各打通一个长方体的洞,在上下底面的中心打通一个圆柱形 的洞.已知正方体边长为10厘米,侧面上的洞口是边长为4厘米的正方形,上... | 立体切拼、立体图形公式 | 三视图与表面积 | ocr_or_visual_missing | 题目强依赖图形，当前审计未运行多模态题块识别，需用题块图片复核。 |
| 立体图形.pdf | 8 | 18 | 水平放置的正方体的六个面分别用“前面、后面、上面、下面、左面、右面”表示.如下图,是一个正方体的平面 展开图,若图中的“似”表示正方体的前面,“锦”表示右面,“程”表示下面,则“祝... | 正方体相对面、展开图剪拼 | 三视图与表面积 | ocr_or_visual_missing | 题目强依赖图形，当前审计未运行多模态题块识别，需用题块图片复核。 |
| 立体图形.pdf | 9 | 19 | A、 B、 C、 D、 如图是一个小正方体的展开图,把展开图折叠成小正方体后,有“建”字一面的相对面上的字是( ). 和 谐 社 会 | 正方体相对面、展开图剪拼 | 三视图与表面积 | ocr_or_visual_missing | 题目强依赖图形，当前审计未运行多模态题块识别，需用题块图片复核。 |
| 立体图形.pdf | 10 | 21 | A、 B、 C、 D、 如图所示的正方体的展开图是( ). | 展开图剪拼、正方体相对面 | 三视图与表面积 | ocr_or_visual_missing | 题目强依赖图形，当前审计未运行多模态题块识别，需用题块图片复核。 |
| 立体图形.pdf | 10 | 22 | 每个小正方体的棱长为2,求露在外面的面积.(在桌上,底面积不算) | 三视图与表面积、立体图形公式 | 三视图与表面积 | ocr_or_visual_missing | 题目强依赖图形，当前审计未运行多模态题块识别，需用题块图片复核。 |

## TOP 5 优先修复问题
1. 重点面积模型题在没有稳定上游模型事实时，fallback 很容易只给出 composite_area_model，导致 primary 展示变宽。
2. 一半模型、等积变形、蝴蝶/燕尾等题多数依赖图形结构，题干只写“如图”或“中点/比例”，纯文本不足以稳定识别具体模型。
3. 圆与扇形题能被部分专项 fallback 命中，但普通圆弧/阴影题仍可能退化为 circle_sector_formula 或 composite_area_model。
4. 立体几何中展开图、相对面、表面涂色计数、最短路径等子类型缺少足够细的 fallback 映射，容易被 solid_formula 吸收。
5. 棋盘/坐标题含“正方形棋盘、横线竖线、坐标”等空间词，存在误进 dim2 几何的风险，需要 domain gate 区分规则/坐标题。

## 最小迭代建议
1. 保留现有评分矩阵，只在 dim2 几何候选生成和知识点展示层加优先级保护。
2. 对一半模型、等积变形、蝴蝶、燕尾、鸟头、风筝、相似模型建立少量直接映射；当它们与 `composite_area_model` 同时出现时，具体模型必须作为 primary。
3. `composite_area_model` 只在没有具体模型、割补、圆扇形、立体子类证据时作为 primary；否则降为 supporting/background。
4. 针对图形强依赖但题干缺图的样本，报告展示增加 OCR/图片证据不足 warning，不把宽泛 fallback 当成稳定知识点。
5. 增加棋盘/坐标/规则题 domain gate，避免非几何规则题因“正方形棋盘、横线竖线”进入 dim2 几何。

## 建议新增测试
- 几何模型卷 Q2/Q4/Q17：中点/一半模型不应被组合图形面积覆盖。
- 几何模型卷 Q13/Q14/Q15/Q20/Q22：蝴蝶/燕尾/面积比例链出现时，primary 不得是 `composite_area_model`。
- 平面几何 Q6/Q10/Q12/Q15/Q16/Q18/Q21/Q29：圆与扇形割补不应降级为普通组合图形面积。
- 立体图形 Q18/Q19/Q20/Q21：展开图/相对面不应统一展示为立体图形公式。
- 平面几何 Q22/Q28：棋盘坐标/规则题不应误进 dim2 几何。

## 全量结构化表
| file | page | question_no | question_text | is_geometry_candidate | expected_geometry_model | actual_geometry_model_labels | knowledge_range | dim2_level | status | issue_type | suggested_fix |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 立体图形.pdf | 1 | 1 | 下图中的1、2是两块形状不同的铁皮,将每块铁皮弯折后焊接成一个无盖的长方体铁桶(2号焊接成的是一个 底面为正方形的无盖长方体),比较两种铁皮焊接成铁桶后的装水情况( ). A、1号... | True | 展开图剪拼、立体图形公式 | 水位体积、立体图形公式 | K5 / 高思导引五六年级 | L5 | suspicious | display_inaccurate | 题目不是单纯直接公式题；若仅按基础公式展示，会误呈现结构负担。 |
| 立体图形.pdf | 1 | 2 | 如下图,将长方形绕轴旋转一周,得到的立体图形是 ,它的体积是 立方厘米. | True | 滚动与旋转、立体图形公式 | 三视图与表面积 | K5 / 高思导引五六年级 | L5 | needs_manual_review | ocr_or_visual_missing | 题目强依赖图形，当前审计未运行多模态题块识别，需用题块图片复核。 |
| 立体图形.pdf | 2 | 3 | 修建一个圆柱形的沼气池,底面直径8米,深度是底面直径的 ,在池内的四壁和下底抹上水泥,抹水泥部分的面 积是多少平方米? | True | 立体图形公式 | uncertain |  |  | wrong | dim2_false_negative | 几何题未进入 dim2，应补充几何候选门禁或提升题块图像证据稳定性。 |
| 立体图形.pdf | 2 | 4 | 爸爸送给乐乐一个圆锥形的玩具(如图).这个玩具的体积是多少立方厘米?如果用一个长方体纸盒包装它,制作 纸盒至少需要多少平方厘米的纸板?(接口处忽略不计,π取3.14). | True | 立体图形公式 | 组合图形面积 | K2 / 校内五年级 | L3 | suspicious | display_inaccurate | 当前只落到宽泛组合图形面积；需要人工确认是否有更具体的割补、比例、圆扇形或立体模型。 |
| 立体图形.pdf | 3 | 5 | 一个圆柱体的容器的底部放着一块正方体铅块,现在打开水⻰头向容器内注水(匀速注入)。15秒钟时水恰好没过 铅块的上表面,又过了1分半钟,水恰好注满了容器。若容器的高度是24厘米,铅块... | True | 水位体积、立体图形公式 | uncertain |  |  | wrong | dim2_false_negative | 几何题未进入 dim2，应补充几何候选门禁或提升题块图像证据稳定性。 |
| 立体图形.pdf | 3 | 6 | 圆柱和圆锥的体积之比是2:1,其中底面半径之比是2:3,则高之比是 . | True | 立体图形公式、面积比例关系 | uncertain |  |  | wrong | dim2_false_negative | 几何题未进入 dim2，应补充几何候选门禁或提升题块图像证据稳定性。 |
| 立体图形.pdf | 3 | 7 | 一根长方体木料,正好可以锯成两个同样的正方体,这时表面积增加了24平方厘米,这根长方体木料的表面积是 平方厘米. | True | 立体切拼、立体图形公式 | 立体图形公式 | K2 / 校内五年级 | L2 | suspicious | display_inaccurate | 实际输出只命中泛化公式/组合图形，缺少更具体的几何子类型展示。 |
| 立体图形.pdf | 4 | 8 | 一个圆锥的底面周长是25.12厘米,高是4厘米.从圆锥的顶点沿着高将它切成两半,表面积之和比原圆锥的表面 积增加了 平方分米. | True | 立体切拼、立体图形公式 | 立体图形公式 | K2 / 校内五年级 | L2 | suspicious | display_inaccurate | 实际输出只命中泛化公式/组合图形，缺少更具体的几何子类型展示。 |
| 立体图形.pdf | 4 | 9 | 大圆柱的高是小圆柱的2倍,大圆柱的侧面积是小圆柱侧面积的12倍,大圆柱的体积是小圆柱体积的 倍. | True | 立体图形公式、面积比例关系 | 立体图形公式 | K2 / 校内五年级 | L2 | suspicious | display_inaccurate | 实际输出只命中泛化公式/组合图形，缺少更具体的几何子类型展示。 |
| 立体图形.pdf | 4 | 10 | 将一个正方体涂成红色,再每面等距离切若干刀,得到若干个同样大小的小正方体.若在这些小正方体中,一面 涂有红色的共有294个,则两面涂有红色和三面涂有红色的总共有 个. | True | 几何计数、立体图形公式 | uncertain |  |  | wrong | dim2_false_negative | 几何题未进入 dim2，应补充几何候选门禁或提升题块图像证据稳定性。 |
| 立体图形.pdf | 5 | 11 | (2024GA)将若干个体积相同的小正方体木块拼成一个大正方体,然后将大正方体的表面涂满红色.若将其拆开 后,只有一面涂成红色的小正方体木块的个数恰好是只有两面涂成红色的小正方体木... | True | 几何计数、立体图形公式 | uncertain |  |  | wrong | dim2_false_negative | 几何题未进入 dim2，应补充几何候选门禁或提升题块图像证据稳定性。 |
| 立体图形.pdf | 5 | 12 | (2022 GDFZ)把长,宽,高分别为8厘米,7厘米,5厘米的长方体表面涂色,然后切成棱长为1厘米的小正方体, 三面涂色的小正方体比两面涂色的小正方体少 (填分数). | True | 几何计数、立体图形公式 | uncertain |  |  | wrong | dim2_false_negative | 几何题未进入 dim2，应补充几何候选门禁或提升题块图像证据稳定性。 |
| 立体图形.pdf | 6 | 13 | (2024 THSS)如图,在一个正方体的两对侧面的中心各打通一个长方体的洞,在上下底面的中心打通一个圆柱形 的洞.已知正方体边长为10厘米,侧面上的洞口是边长为4厘米的正方形,上... | True | 立体切拼、立体图形公式 | 三视图与表面积 | K5 / 高思导引五六年级 | L5 | needs_manual_review | ocr_or_visual_missing | 题目强依赖图形，当前审计未运行多模态题块识别，需用题块图片复核。 |
| 立体图形.pdf | 6 | 14 | (2024 GDFZ)有一圆柱形油罐底面的周长为12厘米,高为9厘米,一只老鼠从距底面1厘米的A处,爬行到对角的B 处吃⻝物,它爬行的最短路线为多少厘米? | True | 展开图剪拼、立体图形公式 | uncertain |  |  | wrong | dim2_false_negative | 几何题未进入 dim2，应补充几何候选门禁或提升题块图像证据稳定性。 |
| 立体图形.pdf | 7 | 15 | (2024 BYSS)一个底面半径是6厘米的圆柱形玻璃器皿里装有一部分水,水中漫没着一个高9厘米的圆锥体铅锤. 当铅锤从水中取出后,水面下降了0.5厘米,这个圆锥体的底面积是多少平... | True | 水位体积、立体图形公式 | 立体图形公式 | K2 / 校内五年级 | L2 | suspicious | display_inaccurate | 实际输出只命中泛化公式/组合图形，缺少更具体的几何子类型展示。 |
| 立体图形.pdf | 7 | 16 | (2024 ZCGF)将若干个棱长为a 的小立方块摆成如图所示的几何体. (1)求该几何体的表面积. (2)依图中摆放方法类似,如果几何体摆放了24层,求该几何体的表面积. | True | 三视图与表面积、立体切拼 | 组合图形面积 | K2 / 校内五年级 | L3 | suspicious | display_inaccurate | 实际输出只命中泛化公式/组合图形，缺少更具体的几何子类型展示。 |
| 立体图形.pdf | 8 | 17 | (2024 HPJX)一块底面半径6cm,高12cm的圆锥形钢材,把它熔铸成一根横截面半径是1cm的圆柱形钢条,这根 钢条长多少厘米? | True | 立体图形公式 | uncertain |  |  | wrong | dim2_false_negative | 几何题未进入 dim2，应补充几何候选门禁或提升题块图像证据稳定性。 |
| 立体图形.pdf | 8 | 18 | 水平放置的正方体的六个面分别用“前面、后面、上面、下面、左面、右面”表示.如下图,是一个正方体的平面 展开图,若图中的“似”表示正方体的前面,“锦”表示右面,“程”表示下面,则“祝... | True | 正方体相对面、展开图剪拼 | 三视图与表面积 | K5 / 高思导引五六年级 | L5 | needs_manual_review | ocr_or_visual_missing | 题目强依赖图形，当前审计未运行多模态题块识别，需用题块图片复核。 |
| 立体图形.pdf | 9 | 19 | A、 B、 C、 D、 如图是一个小正方体的展开图,把展开图折叠成小正方体后,有“建”字一面的相对面上的字是( ). 和 谐 社 会 | True | 正方体相对面、展开图剪拼 | 三视图与表面积 | K5 / 高思导引五六年级 | L5 | needs_manual_review | ocr_or_visual_missing | 题目强依赖图形，当前审计未运行多模态题块识别，需用题块图片复核。 |
| 立体图形.pdf | 9 | 20 | 下面是一个正方体和它的展开图,四边APQC是正方体的一个截面,请把截面的四条线段AC、CQ、QP、PA画在展 开图相应的位置上. | True | 展开图剪拼、立体切拼 | uncertain |  |  | wrong | dim2_false_negative | 几何题未进入 dim2，应补充几何候选门禁或提升题块图像证据稳定性。 |
| 立体图形.pdf | 10 | 21 | A、 B、 C、 D、 如图所示的正方体的展开图是( ). | True | 展开图剪拼、正方体相对面 | 三视图与表面积 | K5 / 高思导引五六年级 | L5 | needs_manual_review | ocr_or_visual_missing | 题目强依赖图形，当前审计未运行多模态题块识别，需用题块图片复核。 |
| 立体图形.pdf | 10 | 22 | 每个小正方体的棱长为2,求露在外面的面积.(在桌上,底面积不算) | True | 三视图与表面积、立体图形公式 | 三视图与表面积 | K5 / 高思导引五六年级 | L5 | needs_manual_review | ocr_or_visual_missing | 题目强依赖图形，当前审计未运行多模态题块识别，需用题块图片复核。 |
| 立体图形.pdf | 11 | 23 | 一个密封的长方体水箱,从里面量长60厘米,宽30厘米,高30厘米.当水箱如下左图放置时,水深为20厘米,当 水箱如下右图放置时,水深 厘米. | True | 水位体积、立体图形公式 | uncertain |  |  | wrong | dim2_false_negative | 几何题未进入 dim2，应补充几何候选门禁或提升题块图像证据稳定性。 |
| 立体图形.pdf | 11 | 24 | 如图,转动长方形ABCD,生成两个不同的圆柱,图(1)的底面半径等于 cm,图(2)的体积等于 .(π取3) | True | 滚动与旋转、立体图形公式 | 组合图形面积 | K2 / 校内五年级 | L3 | suspicious | display_inaccurate | 实际输出只命中泛化公式/组合图形，缺少更具体的几何子类型展示。 |
| 立体图形.pdf | 11 | 25 | 一个圆柱体和一个圆锥体,底面半径之比为1:2,高之比为2:3,它们的体积比为 . | True | 立体图形公式、面积比例关系 | uncertain |  |  | wrong | dim2_false_negative | 几何题未进入 dim2，应补充几何候选门禁或提升题块图像证据稳定性。 |
| 立体图形.pdf | 12 | 26 | 四个同样大小的圆柱拼成一个高为40厘米的大圆柱时,表面积减少了72平方厘米,原来小圆柱的体积是 立方厘米. | True | 立体切拼、立体图形公式 | 立体图形公式 | K2 / 校内五年级 | L2 | suspicious | display_inaccurate | 实际输出只命中泛化公式/组合图形，缺少更具体的几何子类型展示。 |
| 小升初几何模型.pdf | 1 | 1 | 如图,长方形AFEB和长方形FDCE拼成了长方形ABCD,长方形ABCD的长是20,宽是12,则它内部阴影部分的面 积是 . | True | 割补法、组合图形面积 | 组合图形面积 | K2 / 校内五年级 | L3 | suspicious | display_inaccurate | 实际输出只命中泛化公式/组合图形，缺少更具体的几何子类型展示。 |
| 小升初几何模型.pdf | 1 | 2 | 如图,在梯形ABCD中,BC=2AD,E、F分别为BC、AB的中点。连接EF、FC。 若三角形EFC的面积为a,则梯形ABCD的面积是 。 | True | 一半模型、等高面积关系 | 组合图形面积 | K2 / 校内五年级 | L3 | wrong | model_overridden_by_broad_label | 具体几何模型应作为 primary；composite_area_model 只应作为 supporting/background。 |
| 小升初几何模型.pdf | 2 | 3 | (2023 ZCGF)如图,阴影部分的面积是 . | True | 圆与扇形割补、割补法 | 组合图形面积 | K2 / 校内五年级 | L3 | suspicious | display_inaccurate | 实际输出只命中泛化公式/组合图形，缺少更具体的几何子类型展示。 |
| 小升初几何模型.pdf | 2 | 4 | 已知正方形ABCD面积为1,E、F、G分别是BC、DC 和AD边的中点,求阴影部分的面积是多少? | True | 一半模型、等积变形 | 组合图形面积 | K2 / 校内五年级 | L3 | wrong | model_overridden_by_broad_label | 具体几何模型应作为 primary；composite_area_model 只应作为 supporting/background。 |
| 小升初几何模型.pdf | 3 | 5 | 如图所示,A、B、C、D是边长为10的正八边形的对角线交点,那么四边形 ABCD 的面积为 . | True | 割补法、几何计数 | 组合图形面积 | K2 / 校内五年级 | L3 | suspicious | display_inaccurate | 实际输出只命中泛化公式/组合图形，缺少更具体的几何子类型展示。 |
| 小升初几何模型.pdf | 3 | 6 | (2023 JGF)如图,三角形ABC中, ,三角形COD的面积是4,三角形COE的面积是3,则三角形ABC的 面积是多少? | True | 面积比例关系 | 组合图形面积 | K2 / 校内五年级 | L3 | suspicious | display_inaccurate | 实际输出只命中泛化公式/组合图形，缺少更具体的几何子类型展示。 |
| 小升初几何模型.pdf | 4 | 7 | (2024 ZCGF)如图,长方形被分成了若干块,其中三块的面积标注在图上,阴影部分的面积是多少?(单位:平 方厘米) | True | 面积比例关系、组合图形面积 | 组合图形面积 | K2 / 校内五年级 | L3 | suspicious | display_inaccurate | 实际输出只命中泛化公式/组合图形，缺少更具体的几何子类型展示。 |
| 小升初几何模型.pdf | 4 | 8 | 如图,求如图中阴影部分的面积(精确到0.01, 取3.14). | True | 圆与扇形割补 | 组合图形面积 | K2 / 校内五年级 | L3 | suspicious | display_inaccurate | 实际输出只命中泛化公式/组合图形，缺少更具体的几何子类型展示。 |
| 小升初几何模型.pdf | 5 | 9 | 三角形ABC 中, 是直角,已知 厘米, 厘米, 厘米, ,那么三角形 AMN (阴影部分)的面积是 平方厘米. | True | 一半模型、面积比例关系 | 组合图形面积 | K2 / 校内五年级 | L3 | wrong | model_overridden_by_broad_label | 具体几何模型应作为 primary；composite_area_model 只应作为 supporting/background。 |
| 小升初几何模型.pdf | 5 | 10 | 如图所示,S 阴= cm2. | True | 等积变形、一半模型 | uncertain |  |  | wrong | dim2_false_negative | 几何题未进入 dim2，应补充几何候选门禁或提升题块图像证据稳定性。 |
| 小升初几何模型.pdf | 5 | 11 | 如图, 中, , ,那么 是 的面积的几 分之几? | True | 面积比例关系 | 组合图形面积 | K2 / 校内五年级 | L3 | suspicious | display_inaccurate | 实际输出只命中泛化公式/组合图形，缺少更具体的几何子类型展示。 |
| 小升初几何模型.pdf | 6 | 12 | 如图,点D、E分别是 的边AB、AC的中点,连接DE,将 沿DE翻折,点A正落在BC边的点F上,若 的面积是34,则 的面积是 . | True | 一半模型、等积变形 | 组合图形面积 | K2 / 校内五年级 | L3 | wrong | model_overridden_by_broad_label | 具体几何模型应作为 primary；composite_area_model 只应作为 supporting/background。 |
| 小升初几何模型.pdf | 6 | 13 | 如图,三角形ABC的面积为10,AD与BF交于点E,且AE=ED, ,图中阴影部分的面积为 . | True | 蝴蝶模型、面积比例关系 | 组合图形面积 | K2 / 校内五年级 | L3 | wrong | model_overridden_by_broad_label | 具体几何模型应作为 primary；composite_area_model 只应作为 supporting/background。 |
| 小升初几何模型.pdf | 6 | 14 | 如图:三角形ABC中,D为BC中点,CE=2AE,AB=4BF,连接AD,BE,CF,其两两交点分别为G,H,L,三角 形GHI的面积是25,三角形ABC的面积为( ). A、25... | True | 燕尾模型、面积比例关系 | 组合图形面积 | K2 / 校内五年级 | L3 | wrong | model_overridden_by_broad_label | 具体几何模型应作为 primary；composite_area_model 只应作为 supporting/background。 |
| 小升初几何模型.pdf | 7 | 15 | A、31 B、32 C、33 D、34 在下面△ABC中,BF=3AF,BD=3DC,BE=ED,△BEF的面积是9,求△ABC的面积.( ) | True | 燕尾模型、面积比例关系 | uncertain |  |  | wrong | dim2_false_negative | 几何题未进入 dim2，应补充几何候选门禁或提升题块图像证据稳定性。 |
| 小升初几何模型.pdf | 7 | 16 | A、20 B、30 C、40 D、50 如图,三角形ABC被分成7块面积相等的小三角形,其中AC=96厘米,BC=70厘米,则GI的长度为( ). | True | 面积比例关系、相似模型 | 组合图形面积 | K2 / 校内五年级 | L3 | wrong | model_overridden_by_broad_label | 具体几何模型应作为 primary；composite_area_model 只应作为 supporting/background。 |
| 小升初几何模型.pdf | 8 | 17 | 如图,在 中,已知 、 、 分别为 、 、 的中点,且 的面积为50平方厘米,则阴影部 分的面积为 平方厘米. | True | 一半模型 | 组合图形面积 | K2 / 校内五年级 | L3 | wrong | model_overridden_by_broad_label | 具体几何模型应作为 primary；composite_area_model 只应作为 supporting/background。 |
| 小升初几何模型.pdf | 8 | 18 | 如图,正方形ABCD和正方形ECGF并排放置,BF与CD相交于点H,已知AB=4 cm,求阴影部分的面积. | True | 蝴蝶模型、等积变形 | 组合图形面积 | K2 / 校内五年级 | L3 | wrong | model_overridden_by_broad_label | 具体几何模型应作为 primary；composite_area_model 只应作为 supporting/background。 |
| 小升初几何模型.pdf | 9 | 19 | 图中的两个正方形边长分别是10和14厘米,则阴影部分面积是多少平方厘米? | True | 等积变形、割补法 | 组合图形面积 | K2 / 校内五年级 | L3 | wrong | model_overridden_by_broad_label | 具体几何模型应作为 primary；composite_area_model 只应作为 supporting/background。 |
| 小升初几何模型.pdf | 9 | 20 | 如图,正方形ABCD的面积为1, , , 与 相交于 点, 与 相交于 点,那么阴 影三角形 的面积是 . | True | 面积比例关系、蝴蝶模型 | 组合图形面积 | K2 / 校内五年级 | L3 | wrong | model_overridden_by_broad_label | 具体几何模型应作为 primary；composite_area_model 只应作为 supporting/background。 |
| 小升初几何模型.pdf | 10 | 21 | 如图,四边形 和四边形 都是正方形, , ,求阴影部分面积.(π取3) | True | 圆与扇形割补、组合图形面积 | 组合图形面积 | K2 / 校内五年级 | L3 | suspicious | display_inaccurate | 实际输出只命中泛化公式/组合图形，缺少更具体的几何子类型展示。 |
| 小升初几何模型.pdf | 10 | 22 | 如图,在△ABC 中,BD ..DC =1..2,E 是AD 的中点,若△ABC 的面积是120,那么阴影部分面积为 . | True | 面积比例关系、燕尾模型 | 组合图形面积 | K2 / 校内五年级 | L3 | wrong | model_overridden_by_broad_label | 具体几何模型应作为 primary；composite_area_model 只应作为 supporting/background。 |
| 小升初几何模型.pdf | 11 | 23 | A、 B、4..1 C、5..1 D、15..1 点是长方形宽的中点, 点是长方形长的 处,则空白部分与阴影部分面积的比是( ). 161 | True | 一半模型、面积比例关系 | 组合图形面积 | K2 / 校内五年级 | L3 | wrong | model_overridden_by_broad_label | 具体几何模型应作为 primary；composite_area_model 只应作为 supporting/background。 |
| 小升初几何模型.pdf | 11 | 24 | 如图,三角形ABC面积为60,点E是AB中点,点D是AC三等分点,即AD=2CD,则阴影部分的面积为( ). A、14 B、15 C、16 D、17 | True | 一半模型、面积比例关系 | 组合图形面积 | K2 / 校内五年级 | L3 | wrong | model_overridden_by_broad_label | 具体几何模型应作为 primary；composite_area_model 只应作为 supporting/background。 |
| 小升初几何模型.pdf | 11 | 25 | 如图,面积为12平方厘米的正方形 中, 、 是 边上的三等分点,则阴影部分的面积为 . | True | 面积比例关系、等积变形 | 组合图形面积 | K2 / 校内五年级 | L3 | wrong | model_overridden_by_broad_label | 具体几何模型应作为 primary；composite_area_model 只应作为 supporting/background。 |
| 小升初几何模型.pdf | 12 | 26 | 如图,在长方形 中, 是 的中点, 是 的中点, 是 上靠近 的三等分点,如果 厘米, 厘米,则三角形 的面积为 . | True | 面积比例关系、一半模型 | 组合图形面积 | K2 / 校内五年级 | L3 | wrong | model_overridden_by_broad_label | 具体几何模型应作为 primary；composite_area_model 只应作为 supporting/background。 |
| 小升初平面几何.pdf | 1 | 1 | 把一个面积为12.56平方厘米的圆形纸片,剪拼成一个近似的长方形,这个长方形的宽是 厘米,周长是 厘米. | True | 圆与扇形公式、图形变换 | 圆与扇形公式 | K3 / 校内六年级 | L2 | suspicious | display_inaccurate | 实际输出只命中泛化公式/组合图形，缺少更具体的几何子类型展示。 |
| 小升初平面几何.pdf | 1 | 2 | 已知某个台阶的宽度和高度如图所示,现在要在台阶上铺满地毯,则需要地毯的长度是 米. | True | 线段转化 | uncertain |  |  | wrong | dim2_false_negative | 几何题未进入 dim2，应补充几何候选门禁或提升题块图像证据稳定性。 |
| 小升初平面几何.pdf | 2 | 3 | 如图,路线1是以AB为直径的半圆,路线2是四个半圆组成的曲线,一只蚂蚁要从A爬到B,则沿路线1和沿路线2所 走的路程( ). A、路线1少 B、路线2少 C、路线1和路线2一样 D... | True | 圆与扇形公式、线段转化 | 组合图形面积 | K2 / 校内五年级 | L3 | suspicious | display_inaccurate | 实际输出只命中泛化公式/组合图形，缺少更具体的几何子类型展示。 |
| 小升初平面几何.pdf | 2 | 4 | 已知组成网格的小正方形的面积是1,则正方形ACDE的面积S1= ,正方形BCFG的面积S2= ,正 方形ABHI的面积S3= ,由此发现S1、S2、S3三者关系是 . | True | 格点与割补、图形变换 | uncertain |  |  | wrong | dim2_false_negative | 几何题未进入 dim2，应补充几何候选门禁或提升题块图像证据稳定性。 |
| 小升初平面几何.pdf | 3 | 5 | 请将下面等边三角形按要求分割成若干个形状和大小都一样的三角形。 (1)分成2个 (2)分成3个 (3)分成4个 (4)分成6个 | True | 图形变换 | uncertain |  |  | wrong | dim2_false_negative | 几何题未进入 dim2，应补充几何候选门禁或提升题块图像证据稳定性。 |
| 小升初平面几何.pdf | 3 | 6 | 图中阴影部分的面积为 平方厘米.(π取3.14) | True | 圆与扇形割补 | 组合图形面积 | K2 / 校内五年级 | L3 | suspicious | display_inaccurate | 实际输出只命中泛化公式/组合图形，缺少更具体的几何子类型展示。 |
| 小升初平面几何.pdf | 4 | 7 | 图中的数字分别表示两个长方形和一个直角三角形的面积,另一个三角形的面积是 . | True | 等积变形、面积比例关系 | 组合图形面积 | K2 / 校内五年级 | L3 | wrong | model_overridden_by_broad_label | 具体几何模型应作为 primary；composite_area_model 只应作为 supporting/background。 |
| 小升初平面几何.pdf | 4 | 8 | 已知两个正方形的边长分别为4分米和6分米,则图中阴影部分的面积是 平方分米. | True | 等积变形、一半模型 | 组合图形面积 | K2 / 校内五年级 | L3 | wrong | model_overridden_by_broad_label | 具体几何模型应作为 primary；composite_area_model 只应作为 supporting/background。 |
| 小升初平面几何.pdf | 4 | 9 | A、 B、 C、 D、 一个圆和一个正方形的周长都是12.56分米,它们的面积比较,( ). 一样大 正方形大 圆面积大 不能比较 | True | 基本面积公式、圆与扇形公式 | 圆与扇形公式 | K3 / 校内六年级 | L2 | correct |  | 当前输出与人工预期未发现明显冲突。 |
| 小升初平面几何.pdf | 5 | 10 | 如下图,圆周长是12.56厘米,则阴影部分的面积是 平方厘米.(π取3.14) | True | 圆与扇形割补 | 组合图形面积 | K2 / 校内五年级 | L3 | suspicious | display_inaccurate | 实际输出只命中泛化公式/组合图形，缺少更具体的几何子类型展示。 |
| 小升初平面几何.pdf | 5 | 11 | (2024 HPGF)如图,平行四边形ABCD的边BC长10厘米,直角三角形BCE的直角边EC长8厘米,已知阴影部分的总 面积比三角形EFG的面积大10平方厘米,CF的长度是 厘米... | True | 等积变形、割补法 | 组合图形面积 | K2 / 校内五年级 | L3 | wrong | model_overridden_by_broad_label | 具体几何模型应作为 primary；composite_area_model 只应作为 supporting/background。 |
| 小升初平面几何.pdf | 6 | 12 | 三角形ABC是直角三角形,阴影I的面积比阴影II的面积小25平方厘米, 厘米,求BC的长度. | True | 圆与扇形割补 | 组合图形面积 | K2 / 校内五年级 | L3 | suspicious | display_inaccurate | 实际输出只命中泛化公式/组合图形，缺少更具体的几何子类型展示。 |
| 小升初平面几何.pdf | 6 | 13 | 如图,边长为14厘米的正方形中有一块阴影部分,阴影部分的面积是110平方厘米,求 是多少厘米? | True | 面积反求边长、割补法 | 组合图形面积 | K2 / 校内五年级 | L3 | suspicious | display_inaccurate | 实际输出只命中泛化公式/组合图形，缺少更具体的几何子类型展示。 |
| 小升初平面几何.pdf | 7 | 14 | (2024 THSS)房间里地面是长方形形状,是由九个不同的正方形地砖拼接铺成,其中最小的地砖边长是1,求这个 房间的地面面积. | True | 面积比例关系、组合图形面积 | uncertain |  |  | wrong | dim2_false_negative | 几何题未进入 dim2，应补充几何候选门禁或提升题块图像证据稳定性。 |
| 小升初平面几何.pdf | 7 | 15 | (2024GDFZ)计算图中阴影部分的面积. | True | 圆与扇形割补 | 组合图形面积 | K2 / 校内五年级 | L3 | suspicious | display_inaccurate | 实际输出只命中泛化公式/组合图形，缺少更具体的几何子类型展示。 |
| 小升初平面几何.pdf | 8 | 16 | 如图,3个半径为1的圆弧围出了一个区域ABCD.其中,弧AB、AD都是四分之一圆,弧BCD是半个圆.那么,这个 区域的面积为 . | True | 圆与扇形割补 | 组合图形面积 | K2 / 校内五年级 | L3 | suspicious | display_inaccurate | 实际输出只命中泛化公式/组合图形，缺少更具体的几何子类型展示。 |
| 小升初平面几何.pdf | 8 | 17 | (2024 JGF)如图,阴影部分的小正六角星形面积是16平方厘米,大正六角星形面积是多少平方厘米? | True | 相似模型 | 组合图形面积 | K2 / 校内五年级 | L3 | wrong | model_overridden_by_broad_label | 具体几何模型应作为 primary；composite_area_model 只应作为 supporting/background。 |
| 小升初平面几何.pdf | 9 | 18 | (2024 PYHF)如图,一枚半径为1cm的游戏币在边长为6cm的正方形区域内任意移动.在正方形区域内游戏币不 能到达的部分的面积是多少平方厘米? | True | 圆与扇形割补 | 组合图形面积 | K2 / 校内五年级 | L3 | suspicious | display_inaccurate | 实际输出只命中泛化公式/组合图形，缺少更具体的几何子类型展示。 |
| 小升初平面几何.pdf | 9 | 19 | 下面的三个图形都是由正方形和圆形组成的,那么阴影部分面积最大的是 .(填A、B或C) | True | 圆与扇形公式、组合图形面积 | 圆与扇形割补、组合图形面积 | K2 / 校内五年级 | L3 | correct |  | 当前输出与人工预期未发现明显冲突。 |
| 小升初平面几何.pdf | 10 | 20 | 长方形草地ABCD 被分为面积相等的甲、乙、丙和丁四份(如图),其中图形甲的长和宽的比是 ,其 中图形乙的长和宽的比为 : . | True | 面积比例关系、组合图形面积 | 组合图形面积 | K2 / 校内五年级 | L3 | suspicious | display_inaccurate | 实际输出只命中泛化公式/组合图形，缺少更具体的几何子类型展示。 |
| 小升初平面几何.pdf | 10 | 21 | 在一圆中取最大正方形,此圆直径为4,求 . 阴 | True | 圆与扇形割补 | uncertain |  |  | wrong | dim2_false_negative | 几何题未进入 dim2，应补充几何候选门禁或提升题块图像证据稳定性。 |
| 小升初平面几何.pdf | 11 | 22 | 五子棋是一种两人对弈的棋类游戏,规则是:在正方形的棋盘中,由黑方先行,白方后行,轮流落子,下在棋盘 横线与竖线的交叉点上,直到某一方首先在任一方向(横向、纵向或者是斜着的方向)上连... | True | uncertain_non_geometry_board_coordinate | uncertain |  |  | correct |  | 保持非几何棋盘坐标题不进入 dim2。 |
| 小升初平面几何.pdf | 11 | 23 | 如图,长方形 中, , ,点P 与点Q 分别在线段AB 、CB 上运动.点P 与点Q 同时出发,点 P 以每秒2个单位长度的速度从点A →点B →点C 运动,点Q 以每秒1个单位长... | True | 面积比例关系、dynamic_geometry | 组合图形面积 | K2 / 校内五年级 | L3 | suspicious | display_inaccurate | 实际输出只命中泛化公式/组合图形，缺少更具体的几何子类型展示。 |
| 小升初平面几何.pdf | 12 | 24 | 一个三角形三个内角的比是3:3:6,且最短边长为10厘米,则它的面积是 平方厘米. | True | 三角形角度追踪、基本面积公式 | uncertain |  |  | wrong | dim2_false_negative | 几何题未进入 dim2，应补充几何候选门禁或提升题块图像证据稳定性。 |
| 小升初平面几何.pdf | 12 | 25 | 如图所示,三个正方形的面积已经标出,则中间的三角形面积为 . | True | 基本面积公式、图形变换 | 组合图形面积 | K2 / 校内五年级 | L3 | suspicious | display_inaccurate | 实际输出只命中泛化公式/组合图形，缺少更具体的几何子类型展示。 |
| 小升初平面几何.pdf | 12 | 26 | 如图,三角形ABC,三角形ADE,三角形EFG均为正三角形,D、G分别为线段AC、AE的中点,线段AB 长为8.则 多边形ABCDEFG的周长为 . | True | 线段转化、图形变换 | 组合图形面积 | K2 / 校内五年级 | L3 | suspicious | display_inaccurate | 实际输出只命中泛化公式/组合图形，缺少更具体的几何子类型展示。 |
| 小升初平面几何.pdf | 13 | 27 | 如图,在边长为6厘米的正方形ABCD中,以AB为底边作腰长为5厘米的等腰三角形PAB,则三角形PBD的面积等于 平方厘米. | True | 等积变形、基本面积公式 | 组合图形面积 | K2 / 校内五年级 | L3 | wrong | model_overridden_by_broad_label | 具体几何模型应作为 primary；composite_area_model 只应作为 supporting/background。 |
| 小升初平面几何.pdf | 14 | 28 | 国际象棋、中国象棋和围棋号称为世界三大棋种.国际象棋中的“皇后”的威力可比中国象棋中的“⻋”大得多:“皇 后”不仅能控制她所在的行与列中的每一个小方格,而且还能控制“斜”方向的两条... | False | uncertain_non_geometry_board_coordinate | uncertain |  |  | correct |  | 保持非几何棋盘坐标题不进入 dim2。 |
| 小升初平面几何.pdf | 15 | 29 | 如图,正方形边长为2厘米,以圆孤为分界线的甲、乙两部分面积的差(大的减去小的)是多少平方厘米?(π取 3.14) | True | 圆与扇形割补 | 圆与扇形割补、组合图形面积 | K2 / 校内五年级 | L3 | suspicious | display_inaccurate | 组合图形面积可作为背景，但展示层应优先显示更具体的模型或方法。 |
| 小升初平面几何.pdf | 15 | 30 | 凹四边形ABCD的各边长度如图所示,已知 ,那么凹四边形的面积为 .(其中 , ) | True | 割补法、基本面积公式 | 组合图形面积 | K2 / 校内五年级 | L3 | suspicious | display_inaccurate | 实际输出只命中泛化公式/组合图形，缺少更具体的几何子类型展示。 |

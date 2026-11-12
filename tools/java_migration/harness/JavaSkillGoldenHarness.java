// #Created By AiCoding(codex)
// 迁移一致性校验用的 Java 侧“标准答案”生成器：用 Java 项目编译产物 GroovyScriptEngine
// 直接执行 target/classes/agent/skills/<name>/scripts/{assembly,extract}.groovy，
// 输入为 staging/mock-gateway 下的 mock 响应，输出每个 Skill 的 assembly 请求与 extract 结果（每行 “<id>\t<结果>”）。
// Python Skill 在 mock 模式下的填写结果应与这里的输出一致。
// 用法：java -cp <cp> JavaSkillGoldenHarness <mock-gateway 目录>

import com.agile.agent.pdf.parse.agent.common.GroovyScriptEngine;

import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.Path;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;

public class JavaSkillGoldenHarness {

    private static void out(String id, Object value) {
        String text = String.valueOf(value).replace("\r", "\\r").replace("\n", "\\n");
        System.out.println(id + "\t" + text);
    }

    private static Map<String, Object> raw(String body) {
        Map<String, Object> m = new LinkedHashMap<>();
        m.put("statusCode", 200);
        m.put("body", body);
        return m;
    }

    private static Map<String, Object> ctx(Map<String, Object> params, Map<String, Object> completedKv) {
        Map<String, Object> c = new LinkedHashMap<>();
        c.put("paramContext", params);
        c.put("completedKv", completedKv);
        return c;
    }

    /** 安全执行：异常时输出异常根因，便于和 Python 侧的 not_found/失败对照。 */
    private interface Action { Object run() throws Exception; }

    private static void safe(String id, Action action) {
        try {
            out(id, action.run());
        } catch (Throwable e) {
            Throwable root = e;
            while (root.getCause() != null) {
                root = root.getCause();
            }
            out(id, "EXCEPTION: " + root.getClass().getSimpleName() + ": " + root.getMessage());
        }
    }

    public static void main(String[] args) throws Exception {
        Path mockDir = Path.of(args[0]);
        String sms = Files.readString(mockDir.resolve("querySMSSendInfo.xml"), StandardCharsets.UTF_8);
        String smsNoData = Files.readString(mockDir.resolve("querySMSSendInfo.13900000000.xml"), StandardCharsets.UTF_8);
        String balance = Files.readString(mockDir.resolve("BOSS_QryBalanceFlowLog.xml"), StandardCharsets.UTF_8);
        String balanceFail = Files.readString(mockDir.resolve("BOSS_QryBalanceFlowLog.13900000000.xml"), StandardCharsets.UTF_8);
        String pretty = Files.readString(mockDir.resolve("cc_pretty_num_info_query.xml"), StandardCharsets.UTF_8);
        String prettyNo = Files.readString(mockDir.resolve("cc_pretty_num_info_query.13900000000.xml"), StandardCharsets.UTF_8);

        GroovyScriptEngine engine = new GroovyScriptEngine();

        // 与 normalizeParamAliases 一致：中文键 + 英文规范键同时存在
        Map<String, Object> params = new LinkedHashMap<>();
        params.put("手机号码", "13900001234");
        params.put("phoneNumber", "13900001234");
        params.put("业务名称", "5G智享套餐（个人版）");
        params.put("opName", "5G智享套餐（个人版）");
        params.put("创建时间", "20261105103012");
        params.put("createTime", "20261105103012");
        Map<String, Object> empty = Map.of();
        Map<String, Object> c0 = ctx(params, empty);

        safe("business-sms.assembly", () -> engine.runAssembly("business-sms", c0).get("request"));
        String businessJson = engine.runExtract("business-sms", c0, raw(sms));
        out("business-sms.extract", businessJson);
        safe("business-sms.extract.nodata", () -> engine.runExtract("business-sms", c0, raw(smsNoData)));

        // 框架把 JSON Object 分解为 _kv:<字段>
        @SuppressWarnings("unchecked")
        Map<String, Object> businessKv = new tools.jackson.databind.ObjectMapper().readValue(businessJson, Map.class);
        Map<String, Object> completed = new LinkedHashMap<>();
        completed.put("_kv:订购短信", businessKv.get("订购短信"));
        Map<String, Object> c1 = ctx(params, completed);

        safe("accept-type.extract", () -> engine.runExtract("accept-type", c1, null));
        safe("accept-type.extract.noBusinessSms", () -> engine.runExtract("accept-type", c0, null));
        safe("second-confirmation-sms.extract", () -> engine.runExtract("second-confirmation-sms", c0, raw(sms)));
        safe("verification-sms.extract", () -> engine.runExtract("verification-sms", c0, raw(sms)));
        safe("original-package-name.assembly", () -> engine.runAssembly("original-package-name", c1).get("request"));
        safe("original-package-name.extract", () -> engine.runExtract("original-package-name", c1, raw(sms)));
        safe("reminder-sms.assembly", () -> engine.runAssembly("reminder-sms", c1).get("request"));
        safe("reminder-sms.extract", () -> engine.runExtract("reminder-sms", c1, raw(sms)));
        safe("renewal-reminder-sms.assembly", () -> engine.runAssembly("renewal-reminder-sms", c1).get("request"));
        safe("renewal-reminder-sms.extract", () -> engine.runExtract("renewal-reminder-sms", c1, raw(sms)));
        safe("number-portability-sms.extract", () -> engine.runExtract("number-portability-sms", c0, raw(sms)));

        Map<String, Object> billParams = new LinkedHashMap<>(params);
        billParams.put("账单", "202611$202611");
        billParams.put("billingCycle", "202611$202611");
        Map<String, Object> cb = ctx(billParams, empty);
        safe("billing-cycle-sms.assembly", () -> engine.runAssembly("billing-cycle-sms", cb).get("request"));
        safe("billing-cycle-sms.extract", () -> engine.runExtract("billing-cycle-sms", cb, raw(sms)));
        safe("billing-cycle-sms.extract.nodata", () -> engine.runExtract("billing-cycle-sms", cb, raw(smsNoData)));

        Map<String, Object> balParams = new LinkedHashMap<>();
        balParams.put("客户号码", "15062667019");
        balParams.put("充值时间", "20260705");
        Map<String, Object> cbal = ctx(balParams, empty);
        safe("qry-balance.assembly", () -> engine.runAssembly("qry-balance", cbal).get("request"));
        safe("qry-balance.extract", () -> engine.runExtract("qry-balance", cbal, raw(balance)));
        safe("qry-balance.extract.fail7003", () -> engine.runExtract("qry-balance", cbal, raw(balanceFail)));
        Map<String, Object> balRange = new LinkedHashMap<>(balParams);
        balRange.put("充值时间", "20260701-20260731");
        safe("qry-balance.extract.range", () -> engine.runExtract("qry-balance", ctx(balRange, empty), raw(balance)));

        Map<String, Object> prettyParams = new LinkedHashMap<>();
        prettyParams.put("手机号码", "15252749921");
        prettyParams.put("phoneNumber", "15252749921");
        Map<String, Object> cp = ctx(prettyParams, empty);
        safe("pretty-number-info.assembly", () -> engine.runAssembly("pretty-number-info", cp).get("request"));
        safe("pretty-number-info.extract", () -> engine.runExtract("pretty-number-info", cp, raw(pretty)));
        safe("pretty-number-info.extract.notPretty", () -> engine.runExtract("pretty-number-info", cp, raw(prettyNo)));
        System.exit(0);
    }
}

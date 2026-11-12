// #Created By AiCoding(codex)
// 迁移一致性校验用的 Java 侧报文生成器：反射调用 Java 项目编译产物
// CommonRequestToolService#toXmlRequest（xml-nytool 实际使用的序列化逻辑），
// 入参 body 按 Groovy assembly.groovy 的 Map 字面量顺序构造（LinkedHashMap），再按 buildGatewayBody 补 process_code/app_id/access_token。
// 输出：每个用例一行 “<id>\t<xml>”，供 _check.py 与 Python build_request_xml(style=java) 逐字比较。

import com.agile.agent.pdf.parse.tool.CommonRequestToolService;

import java.lang.reflect.Method;
import java.util.LinkedHashMap;
import java.util.Map;

public class JavaXmlRequestHarness {

    /** 构造与 buildGatewayBody 一致的报文 Map。 */
    private static Map<String, Object> gatewayBody(String processCode, Map<String, Object> request) {
        Map<String, Object> body = new LinkedHashMap<>(request);
        body.put("process_code", processCode);
        body.putIfAbsent("app_id", "APP");
        body.putIfAbsent("access_token", "TOKEN");
        return body;
    }

    private static Map<String, Object> map(Object... kv) {
        Map<String, Object> m = new LinkedHashMap<>();
        for (int i = 0; i < kv.length; i += 2) {
            m.put((String) kv[i], kv[i + 1]);
        }
        return m;
    }

    public static void main(String[] args) throws Exception {
        CommonRequestToolService service = new CommonRequestToolService(null);
        Method toXml = CommonRequestToolService.class.getDeclaredMethod("toXmlRequest", Map.class);
        toXml.setAccessible(true);

        Map<String, Map<String, Object>> cases = new LinkedHashMap<>();
        // business-sms 等短信 Skill 的 assembly.groovy 输出
        cases.put("querySMSSendInfo", gatewayBody("querySMSSendInfo", map(
                "route_type", "2",
                "route_value", "13900001234",
                "content", map(
                        "userMobile", "13900001234",
                        "startDate", "20261105000000",
                        "endDate", "20261105235959",
                        "sendType", "0",
                        "sendPort", "",
                        "busiType", "0"))));
        // qry-balance assembly.groovy 输出（request_time 由脚本取当前时间，此处固定为样例值，Python 侧无法生成）
        cases.put("BOSS_QryBalanceFlowLog", gatewayBody("BOSS_QryBalanceFlowLog", map(
                "request_type", "1",
                "organ_id", "3001",
                "operator_id", "",
                "route_type", "2",
                "route_value", "15062667019",
                "request_seq", "",
                "request_source", "1",
                "request_time", "20260929181722",
                "verify_code", "1002",
                "content", map("userMobile", "15062667019", "cycle", "202607"))));
        // pretty-number-info assembly.groovy 输出
        cases.put("cc_pretty_num_info_query", gatewayBody("cc_pretty_num_info_query", map(
                "route_type", "2",
                "route_value", "15252749921",
                "content", map("msisdn_list", map("msisdn", "15252749921")))));

        for (Map.Entry<String, Map<String, Object>> e : cases.entrySet()) {
            String xml = (String) toXml.invoke(service, e.getValue());
            System.out.println(e.getKey() + "\t" + xml);
        }
    }
}

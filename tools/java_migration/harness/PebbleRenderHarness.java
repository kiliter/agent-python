// #Created By AiCoding(codex)
// 迁移一致性校验用的 Java 侧渲染器：直接调用 Java 项目编译产物 PebbleTemplateEngine.render()，
// 作为“迁移前”的标准答案。输入（stdin）为 JSON：
//   {"cases":[{"id":"...","template":"<Pebble 正文>","values":{"字段":"值"}}]}
// 输出（stdout）为 JSON：{"<id>":{"ok":true,"text":"..."}|{"ok":false,"error":"..."}}
// values 中缺失或空字符串的字段与 Java 线上行为一致（保留 {{ 字段 }} 占位符）。

import com.agile.agent.pdf.parse.template.PebbleTemplateEngine;
import tools.jackson.databind.ObjectMapper;

import java.io.InputStream;
import java.nio.charset.StandardCharsets;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;

public class PebbleRenderHarness {

    /**
     * 读取全部用例，逐个渲染并输出结果。
     * #Created By AiCoding(codex)
     */
    @SuppressWarnings("unchecked")
    public static void main(String[] args) throws Exception {
        ObjectMapper mapper = new ObjectMapper();
        InputStream in = System.in;
        String input = new String(in.readAllBytes(), StandardCharsets.UTF_8);
        Map<String, Object> root = mapper.readValue(input, Map.class);
        List<Map<String, Object>> cases = (List<Map<String, Object>>) root.get("cases");
        PebbleTemplateEngine engine = new PebbleTemplateEngine();
        Map<String, Object> out = new LinkedHashMap<>();
        for (Map<String, Object> c : cases) {
            String id = String.valueOf(c.get("id"));
            String template = (String) c.get("template");
            Map<String, String> values = new LinkedHashMap<>();
            Object raw = c.get("values");
            if (raw instanceof Map<?, ?> m) {
                for (Map.Entry<?, ?> e : m.entrySet()) {
                    values.put(String.valueOf(e.getKey()), e.getValue() == null ? null : String.valueOf(e.getValue()));
                }
            }
            Map<String, Object> r = new LinkedHashMap<>();
            try {
                r.put("ok", true);
                r.put("text", engine.render(template, values));
            } catch (Exception ex) {
                Throwable cause = ex.getCause() != null ? ex.getCause() : ex;
                r.put("ok", false);
                r.put("error", cause.getClass().getSimpleName() + ": " + cause.getMessage());
            }
            out.put(id, r);
        }
        // 日志框架可能输出到 stdout，结果写入参数指定的文件，避免混杂
        byte[] bytes = mapper.writeValueAsString(out).getBytes(StandardCharsets.UTF_8);
        if (args.length > 0) {
            java.nio.file.Files.write(java.nio.file.Path.of(args[0]), bytes);
        } else {
            System.out.write(bytes);
            System.out.flush();
        }
    }
}

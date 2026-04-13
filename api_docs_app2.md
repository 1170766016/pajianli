# 合同关键信息提取服务 (API V2.0) 接口文档

本文档描述了 **合同关键信息提取服务 (app2)** 的 API 接口规范，旨在为交付和集成提供参考。

---

## 1. 服务概述

本服务通过上传合同文件（PDF 或 Word），利用大语言模型（LLM）自动提取合同中的关键信息（如双方主体、金额、有效期、权利义务等），并以结构化的 JSON 格式返回。

- **运行环境**: 堡垒机（内部网络）
- **开发框架**: FastAPI
- **解决跨域**: 已启用 `CORSMiddleware`，支持全域访问。

---

## 2. 基础信息

| 属性 | 内容 |
| :--- | :--- |
| **基础 URL** | `http://<堡垒机IP>:<端口>` (默认端口: 8001) |
| **数据格式** | 请求: `multipart/form-data` / 响应: `application/json` |
| **文件限制** | 最大 20MB (.pdf, .docx) |

---

## 3. 接口列表

### 3.1 服务健康检查

用于检测服务是否正常在线。

- **URL**: `/`
- **Method**: `GET`
- **响应示例**:
  ```json
  {
    "service": "contract-analyzer-v2",
    "status": "running"
  }
  ```

---

### 3.2 上传合同并分析

上传合同文件并获取关键信息提取结果。

- **URL**: `/analyze`
- **Method**: `POST`
- **Content-Type**: `multipart/form-data`

#### 请求参数 (Body)

| 参数名 | 类型 | 是否必选 | 描述 |
| :--- | :--- | :--- | :--- |
| `file` | File | 是 | 合同文件，支持 `.pdf` 和 `.docx` 格式。 |

#### 响应结构 (Success)

| 字段名 | 类型 | 描述 |
| :--- | :--- | :--- |
| `success` | Boolean | 操作是否成功 |
| `filename` | String | 处理的文件名 |
| `text_length` | Integer | 提取出的文本字符长度 |
| `analyzed_at` | String | 分析完成的时间戳 (ISO 8601) |
| `result` | Object | **结构化分析结果**（详见下表） |

#### `result` 字段详细说明

| 键名 | 描述 |
| :--- | :--- |
| `contract_name` | 合同名称 |
| `contract_type` | 合同类型 |
| `party_a` | 甲方主体名称 |
| `party_b` | 乙方主体名称 |
| `total_amount` | 合同金额 (含币种) |
| `start_date` | 起始日期 |
| `end_date` | 终止日期 |
| `signing_date` | 签订日期 |
| `subject_matter` | 合同标的（80字内） |
| `key_obligations` | 主要权利义务（80字内） |
| `breach_liability` | 违约责任（80字内） |
| `dispute_resolution`| 争议解决方式 |
| `summary` | 合同摘要（150字内） |
| `risk_warnings` | 风险提示列表 (Array) |

#### 响应示例 (200 OK)

```json
{
  "success": true,
  "filename": "房屋租赁合同.pdf",
  "text_length": 1250,
  "analyzed_at": "2026-04-13T21:05:00.123456",
  "result": {
    "contract_name": "北京市房屋租赁合同(自行成交版)",
    "contract_type": "租赁合同",
    "party_a": "张三",
    "party_b": "李四",
    "total_amount": "人民币 36,000 元",
    "start_date": "2026-05-01",
    "end_date": "2027-04-30",
    "signing_date": "2026-04-10",
    "subject_matter": "租赁位于朝阳区某小区的住宅一套，用途为居住。",
    "key_obligations": "甲方交付合格房屋；乙方按期支付租金，不得擅自转租。",
    "breach_liability": "逾期交房或付租超过15日，违约金按月租金200%计算。",
    "dispute_resolution": "提交北京仲裁委员会仲裁",
    "summary": "本合同为期一年的住宅租赁协议，约定了月租金3000元，支付方式为押一付三。",
    "risk_warnings": [
      "乙方转租限制条款较为严格",
      "未约定提前退租时的押金扣除细节"
    ]
  }
}
```

---

## 4. 异常处理

| 状态码 | 含义 | 场景描述 |
| :--- | :--- | :--- |
| **400** | Bad Request | 文件格式不正确（非 .pdf 或 .docx） |
| **413** | Payload Too Large | 上传的文件超过了 20MB 的限制 |
| **422** | Unprocessable Entity | 文件解析失败或内容为空 |
| **500** | Internal Server Error | 大模型调用失败或服务器内部逻辑错误 |

---

## 5. 交互调试

部署成功后，可以通过自带的交互文档进行测试：
- **Swagger UI**: `http://<堡垒机IP>:<端口>/docs`
- **ReDoc**: `http://<堡垒机IP>:<端口>/redoc`

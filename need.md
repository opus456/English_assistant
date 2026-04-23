## 项目需求文档：CET6-Daily-Flow (英语六级每日阅读自动化工作流)
1. 项目概述
项目目标：开发一个自动化系统，每日抓取高质量英语文章，利用大模型（LLM）生成符合英语六级（CET-6）标准的阅读题目、深度解析及词汇学习包，并最终以 PDF 格式推送至平板端（通过 QQ 机器人）。
核心受众：学习英语的学生，追求平板手写体验及高效复习。

1. 核心功能需求
2.1 数据抓取模块 (Scraper)
素材来源：合法授权/开放的英文媒体（如 BBC, The Guardian, China Daily, Economist）。

素材筛选：

长度：500 - 800 词。

难度：蓝思等级（Lexile）介于 1000L - 1200L（对应六级水平）。

主题：覆盖社会科学、科技前沿、文化教育等六级高频话题。

输出：纯文本内容 + 原始来源 URL。

2.2 AI 智能加工模块 (AI Engine)
输入：抓取的原始文本。

任务 A：真题模拟出题

题型：交替生成“仔细阅读（Multiple Choice）”或“长篇匹配（Paragraph Matching）”。

标准：参考历年六级真题逻辑，干扰项需具有迷惑性。

任务 B：深度学习包生成

词汇提取：筛选文中的 B2-C1 级生词（约 10-15 个），提供中文释义、音标及例句。

长难句拆解：选取 2-3 个语法复杂的句子，进行成分分析（主谓宾、从句结构）及翻译。

答案解析：提供题目答案，并附带详细的定位分析及排除理由。

2.3 排版与 PDF 转换模块 (Layout Engine)
UI 风格：清爽、透明感现代轻技术风格（Light Theme）。

文件 A：Daily_Reading_Test.pdf (试卷卷)

布局：A4 画幅，大页边距（方便平板手写笔记）。

内容：文章正文 + 题目。

文件 B：Daily_Reading_Analysis.pdf (解析卷)

内容：答案卡片 + 词汇表 + 长难句图解 + 详细解析。

2.4 推送系统 (Distribution)
触发机制：每日早晨（如 07:30）自动触发。

推送渠道：QQ 机器人私聊发送文件（基于 OneBot 协议/NoneBot 框架）。

3. 技术约束与规范
3.1 技术栈 (Tech Stack)
语言：Python 3.10+

爬虫：Playwright (Chromium)

LLM API：DeepSeek-V3 或 GPT-4o

PDF 生成：WeasyPrint (HTML/CSS to PDF)

数据库：MySQL (记录每日任务状态、生词频率)

3.2 数据结构 (JSON Interface)
AI 输出必须遵循以下严格的 JSON 格式：

JSON
{
  "article_metadata": { "title": "", "source": "", "difficulty": "CET-6" },
  "exercise": {
    "type": "multiple_choice",
    "questions": [
      { "id": 1, "question": "", "options": {"A":"","B":"","C":"","D":""}, "answer": "A", "explanation": "" }
    ]
  },
  "learning_package": {
    "vocabulary": [ { "word": "", "phonetic": "", "definition": "", "example": "" } ],
    "syntax_analysis": [ { "original": "", "breakdown": "", "translation": "" } ]
  }
}
4. 非功能性需求
可部署性：必须支持 Docker 容器化部署。

稳定性：爬虫需具备异常处理机制（Retry），LLM 调用需处理 Token 超限问题。

分享性：代码结构清晰，支持通过环境变量配置 API Key，便于非商业分享。

5. 待办开发清单 (Action Plan)
[ ] Phase 1: 编写 Python 爬虫脚本，能够稳定获取文章。

[ ] Phase 2: 编写核心 Prompt，并在大模型 Playground 测试出题质量。

[ ] Phase 3: 编写 HTML/CSS 模板，使用 WeasyPrint 生成 PDF。

[ ] Phase 4: 集成 NoneBot2，实现文件自动推送。

[ ] Phase 5: 编写 Dockerfile，部署至服务器。
# openVman 中國供應鏈與替代方案

調查日期：2026-09-30。本報告依專案程式碼與官方文件整理，這次只更新報告。

[TOC]

## 本次調查結論

**根據這次調查，目前沒有找到比 MatesX／DHLiveMini2 更適合本專案的替代品。**

本專案需要同時保留三件事：**真人仿真效果、瀏覽器本地對嘴、低伺服器算圖成本。**MatesX／DHLiveMini2 目前最符合這個組合。

Azure、D-ID、HeyGen 可以做真人虛擬人，但畫面由遠端伺服器計算，再持續傳給瀏覽器。改用這些服務，會增加按使用量計費的服務費、GPU 或影片傳輸支出。D-ID 企業自架則把這些費用改由自己的主機承擔。[^didself][^azureavatar][^liveavatar]

**目前客戶願意付的價格與租用主機成本已經難以打平，增加遠端 Avatar 算圖會進一步提高營運成本。**因此報告保留各家做法供比較，現階段繼續採用 MatesX／DHLiveMini2 的瀏覽器本地運算架構。

## 先處理 DHLiveMini2

**DHLiveMini2 是目前真人虛擬人的核心，替換它的工作量最大。**它負責把角色素材和聲音合成為會說話的真人畫面。更換後，角色製作、對嘴、畫面播放都要重新接。

本次查過的其他真人技術有三種：

- **D-ID**：產生真人說話畫面。可用雲端 API，也有企業自架方案。
- **Azure、HeyGen LiveAvatar**：建立真人角色，由雲端產生說話畫面。
- **NVIDIA Audio2Face + MetaHuman**：重新製作寫實 3D 人物，再用聲音控制臉部動畫。

下表說明各家的真人製作方式與運算位置。

## 現在的虛擬人怎麼運作

目前 openVman 使用兩份準備好的角色素材：

- `01.webm`：角色影片。
- `combined_data.json.gz`：角色驅動資料。

開啟前台時，瀏覽器載入角色影片、驅動資料和 DHLiveMini2。每次回答時，TTS 先產生聲音，再把聲音送進 DHLiveMini2，讓角色嘴型跟著聲音變化。

流程是：**準備角色素材 → 載入角色 → 產生回答聲音 → 驅動嘴型 → 顯示真人畫面。**

程式位置：`frontend/app/src/composables/useOpenVmanAvatarRuntime.ts` 的 `loadCharacter()`、`pushAudio()`。本專案的角色上傳功能接收影片與驅動資料；照片轉角色的工具需另外盤點。

## 替代方案怎麼建立角色、怎麼對嘴

**建立角色與讓角色說話，是兩個階段。**建立角色時提供照片或影片；之後每次對話，把文字或聲音送給服務，服務會產生已經對好嘴型的畫面。

### 建立人物需要的素材

| 方案 | 建立人物需要的素材 |
| --- | --- |
| D-ID | 照片型用一張照片；影片型用真人錄影 [^didapi] |
| Azure | 一張照片，或至少 10 分鐘真人錄影 [^azureavatar] |
| HeyGen LiveAvatar | 一張照片，或約 2 分鐘真人錄影 [^liveavatar] |
| NVIDIA + MetaHuman | 先製作寫實 3D 人物，再接臉部動畫 [^a2f] |

D-ID 企業自架可用官方角色或製作專屬角色，錄製規格由 D-ID 提供。[^didself]

### 說話時怎麼對嘴

| 方案 | 聲音與對嘴的處理方式 | 跑在哪裡 |
| --- | --- | --- |
| D-ID 雲端 | 接文字或自己的 TTS 音訊，由 D-ID 產生同步嘴型的真人畫面 | D-ID 雲端 [^didapi] |
| D-ID 企業自架 | 接自己的 AI 回答和 TTS，由自架軟體產生真人畫面 | 自有 GPU 主機／雲端帳號 [^didself] |
| Azure | 送文字，由 Azure 同時產生聲音與同步嘴型的畫面 | Azure 雲端 [^azureavatar] |
| HeyGen LiveAvatar | LITE 模式接自己的 TTS 音訊，由 LiveAvatar 產生同步嘴型的畫面 | LiveAvatar 雲端 [^liveavatar] |
| NVIDIA + MetaHuman | Audio2Face 計算臉部動作，Unreal 繪製人物畫面 | 自有主機，通常需 GPU [^a2f] |

因此，照片／影片型服務通常把對嘴包含在產品裡。openVman 要接它們提供的介面，取得會說話的畫面。NVIDIA 路線則要自己把臉部動畫和 3D 繪圖接起來。

### 各方案接入後會改哪些地方

**D-ID 音訊接入與 LiveAvatar LITE 可以接現有 Brain 和 TTS。**角色要重新建立，畫面改由服務商算好再傳回瀏覽器，新增持續的遠端運算與串流費用。[^didapi][^liveavatar]

**D-ID 企業自架把 Avatar 算圖放到自己的 GPU 主機。**官方收取年度授權與串流用量費，另外還有自己的 GPU 和網路支出。[^didself]

**Azure 的接法是把文字送進 Azure，再拿到聲音和對嘴畫面。**聲音與畫面在 Azure 端處理。自訂真人角色需要申請使用資格和取得本人同意。[^azureavatar]

**NVIDIA 路線使用重新製作的寫實 3D 人物。**要處理人物建模、臉部綁定、材質、燈光、GPU 渲染及影片傳輸，工作量大。[^a2f]

現在 DHLiveMini2 在每位使用者的瀏覽器運算。改成伺服器產生畫面後，同時有多少人使用，就會影響 GPU 和網路費用。替代方案要一起比較畫質、延遲和多人使用的成本。

### 公司與授權也要查

| 方案 | 要查的具體項目 |
| --- | --- |
| D-ID | 自架軟體授權、角色製作費、更新方式、錄音與人像保存位置 |
| Azure | 可用地區、自訂角色申請、聲音與影片費用、真人授權 |
| HeyGen | 模型來源、研發地點、股權、資料保存與第三方服務；目前先列功能候選 |
| NVIDIA + Unreal | NVIDIA 的程式與模型各有授權；Epic 曾有騰訊少數股權投資，採購若限制中國資本參股，要一起查 [^a2f] |

## 其他中國來源元件

「程式來自哪裡」與「資料送去哪裡」分開查。中國來源模型可以放在自己的主機；換成歐美雲服務後，音訊或文件仍會送到供應商。

| 元件 | 專案目前怎麼用 | 來源與問題 | 可替換方案 |
| --- | --- | --- | --- |
| DHLiveMini2 | 真人虛擬人核心，瀏覽器本地算圖 | 上游 DH_live／MatesX；角色商用與模型授權要分開看 [^dh] | 目前保留 MatesX／DHLiveMini2；其他真人方案會改變架構與成本 |
| BGE-M3、FlagEmbedding | 預設知識庫向量模型 | 北京智源，MIT 授權 [^bge] | 已接 OpenAI／Gemini／Voyage；自架可研究 Microsoft E5 |
| Qwen VLM | 啟用 `vlm` profile 才使用 | 阿里巴巴，該模型標 Apache-2.0 [^qwen] | Google Gemma、Microsoft Phi，或雲端圖片理解服務 |
| IndexTTS | 啟用服務後使用 | 專案內模型協議要求商用書面許可；官方模型頁標 Apache-2.0，兩份內容不同 [^index] | 已接 GCP TTS／Gemini TTS／AWS Polly |
| VoxCPM、CosyVoice | 外部 TTS 服務，CosyVoice adapter 用於臺語 | OpenBMB／ModelBest／清華、阿里巴巴；聲音與客製模型授權要查 [^vox][^cosy] | 華語可改 GCP；臺語要先試聽替代服務 |
| Xiaomi ASR、SenseVoice | 可選語音辨識，也可能在主服務失敗時接手 | 小米、阿里巴巴；模型授權與實際備援設定要查 [^xiaomi][^sense] | 已接臺灣 MediaTek Breeze、OpenAI；自架可用 Whisper |
| ModelScope | 部分模型／tokenizer 下載來源 | 建置與啟動時可能下載外部檔案 | 先下載到公司管理的儲存庫，固定版本與檔案校驗值 |
| OpenCC、jieba、中文文字處理 | 繁簡轉換、數字讀法等 | 個人／社群套件，依實際套件查發布者與授權 [^text] | 核准後保留，或重寫專案需要的規則 |

Brain 預設文字模型供應商是 Gemini；ASR 預設是 Breeze。其他服務是否在正式環境使用，要看主機設定的 URL 和啟用項目。

## 替換時會碰到哪些工作

| 功能 | 要做的工作 | 最容易漏掉的問題 |
| --- | --- | --- |
| 真人 Avatar | 重新建立角色、接音訊、接影片串流、處理停止說話 | 中文／臺語嘴型、手機播放、多人使用費用 |
| BGE 向量模型 | 重建全部知識庫與記憶索引，查詢也用新模型 | 同樣維度的向量仍可能代表不同意思，舊索引要重新算 |
| 自架 E5 | 新增接法，處理它要求的文字前綴與長度限制 [^e5] | 中文搜尋品質與完整重建索引 |
| Qwen 圖片模型 | 更換服務，測中文字、表格與照片 [^vlmalt] | GPU 記憶體和文字辨識品質 |
| ASR | 更換網址或服務，測專有名詞、噪音、臺語 | Xiaomi 的特定說話者辨識與一般轉錄有功能差異 |
| TTS | 換聲音或服務，測漏字、讀音、延遲與停止播放 | 原本聲音克隆和臺語效果需要重新比較 |
| 自架 Chatterbox | 新增服務接法、準備聲音素材 | 官方列有 CosyVoice 等引用組件，來源仍要逐項查 [^chatter] |
| AvatarForge | 可研究 ETH 的真人影片生成程式 | 官方描述為批次產片；訓練需數小時，套件也含中國來源組件 [^avatarforge] |

更換下載網站只改變下載地點，模型發布者與授權維持原來的內容。

## 備援也要一起改

語音辨識的備援順序包含 `Breeze → Xiaomi → SenseVoice → OpenAI`，程式會依主供應商、偏好與啟用服務調整。只要 Xiaomi／SenseVoice 的網址仍有設定，主服務失敗時就可能送到它們。

TTS 自動選擇順序包含 `IndexTTS → VoxCPM → CosyVoice → Gemini TTS → GCP TTS → AWS Polly → Edge-TTS`，只使用已啟用的服務。

要移除某家供應商，就一起清掉服務網址、帳號選項和專案設定，再讓主服務故障一次，確認備援實際送去哪裡。

## 建議處理順序

1. **保留現有真人核心與本地算圖架構。**以客戶付費能覆蓋營運成本為原則，先處理目前的供應鏈與授權。
2. **把各項支出分開算。**整理語音辨識、AI 模型、TTS、主機、角色授權與下載流量，找出實際虧損來源。
3. **釐清現有 DHLiveMini2 授權。**整理 JS、WASM、模型和角色素材的來源、版本與商用條款；原 JS 內有阿里雲下載分支，用瀏覽器網路紀錄確認實際請求。
4. **處理 IndexTTS 授權差異。**對照實際使用的權重和附帶授權，向上游確認商用條件。
5. **移除不採用的語音備援。**正式環境的啟用網址和程式預設一起檢查。
6. **更換 BGE 時重建索引。**用原本的問題集比較搜尋與回答品質，再切換正式服務。
7. **固定下載檔案。**保存套件、模型、容器版本、校驗值和授權，更新時重新核對。

這份報告已查程式碼與官方文件。候選服務的實際畫質、延遲、費用，由同一組素材測試和正式報價決定。

## 官方資料

[^dh]: [DH_live：模型、瀏覽器版本與形象商用說明](https://github.com/kleinlee/DH_live)。
[^didapi]: [D-ID 照片／影片角色](https://docs.d-id.com/docs/quickstart)、[D-ID 角色類型與串流](https://docs.d-id.com/reference/agents-sdk-overview)、[D-ID 接外部音訊](https://docs.d-id.com/docs/realtime-overview)。
[^didself]: [D-ID 自架：部署方式、自己的 AI／聲音與收費方式](https://www.d-id.com/self-hosting-realtime-avatars/)。
[^azureavatar]: [Azure 自訂真人角色：照片、錄影與聲音](https://learn.microsoft.com/en-us/azure/ai-services/speech-service/text-to-speech-avatar/what-is-custom-text-to-speech-avatar)。
[^liveavatar]: [LiveAvatar 照片與影片角色](https://docs.liveavatar.com/docs/core-concepts/avatars)、[LITE 接自己的語音服務](https://docs.liveavatar.com/docs/lite-mode/overview)。
[^a2f]: [NVIDIA Audio2Face 功能與授權](https://github.com/NVIDIA/Audio2Face-3D/blob/release/README.md)、[搭配 MetaHuman 的做法](https://developer.nvidia.com/blog/simplify-and-scale-ai-powered-metahuman-deployment-with-nvidia-ace-and-unreal-engine-5)、[MetaHuman 授權](https://www.metahuman.com/license?lang=en-US)、[騰訊歷史投資公告](https://static.www.tencent.com/storage/uploads/2019/11/09/b0963ae0fe5736d1d2b1e7fd2bebb57f.pdf)。
[^bge]: [BGE-M3 模型](https://huggingface.co/BAAI/bge-m3)、[FlagEmbedding](https://github.com/FlagOpen/FlagEmbedding)。
[^qwen]: [目前 Qwen 模型](https://huggingface.co/Qwen/Qwen3-VL-4B-Instruct-FP8)。
[^index]: [IndexTTS 1.5 模型協議](https://raw.githubusercontent.com/index-tts/index-tts/v1.5.0/INDEX_MODEL_LICENSE)、[官方模型頁](https://huggingface.co/IndexTeam/IndexTTS-1.5)。
[^vox]: [VoxCPM](https://github.com/OpenBMB/VoxCPM)、[發布團隊](https://openbmb.github.io/VoxCPM-demopage/)。
[^cosy]: [CosyVoice](https://github.com/QwenAudio/CosyVoice)。
[^xiaomi]: [Xiaomi 模型與使用方法](https://huggingface.co/Ease3/Xiaomi-CocktailASR-1)。
[^sense]: [SenseVoice 模型](https://huggingface.co/FunAudioLLM/SenseVoiceSmall)。
[^text]: [實際 Python OpenCC 套件](https://pypi.org/project/opencc-python-reimplemented/)、[jieba](https://github.com/fxsjy/jieba)、[中文讀法處理](https://github.com/wenet-e2e/WeTextProcessing)。
[^e5]: [Microsoft E5 模型與使用規則](https://huggingface.co/intfloat/multilingual-e5-large)。
[^vlmalt]: [Gemma 3](https://huggingface.co/google/gemma-3-4b-it)、[Phi-4 multimodal](https://huggingface.co/microsoft/Phi-4-multimodal-instruct)。
[^chatter]: [Chatterbox 的功能、授權與引用組件](https://github.com/resemble-ai/chatterbox)。
[^avatarforge]: [ETH AvatarForge 的製作方法、時間與依賴](https://github.com/mediatechnologycenter/AvatarForge)。

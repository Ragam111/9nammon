# Scenarios

Each scenario is a task string for `python -m agent_duo "<task>"`. The steps Scout will take are shown so you can check the tool calls in the transcript.

## 1. Summarize a clip from a link

Task: `สรุปประเด็นสำคัญจาก <YouTube หรือ Bilibili link>`

Expected Scout calls: `youtube read <link>` for the title and description, then `youtube subtitle <link>` for the text.
Critic checks that the summary only uses subtitle text and cites the link.
If there are no subtitles, the answer should say that the summary is based on the description only.

## 2. Search by topic and compare videos

Task: `ค้นหาวิดีโอเรื่อง <หัวข้อ> แล้วเปรียบเทียบ 3 คลิปที่ดีที่สุด`

Expected Scout calls: `youtube search "<หัวข้อ>" --limit 5`, then `youtube read` for the top results.
Bilibili can be added by asking for it in the task, which runs `bilibili search`.
Critic compares only the fields Scout actually retrieved (title, channel, date, description).

## 3. Pull setup or demo steps for project work

Task: `จากคลิปสอนตั้งค่า <link> ให้สกัดขั้นตอนที่ต้องทำกับไฟล์ในโปรเจกต์`

Expected Scout calls: `youtube subtitle <link>`.
Limit: Scout cannot open files in this repo. The answer lists the steps and the file names the video mentions, and marks them as unverified until someone checks the repo.
A tool that reads project files is needed for the full version of this scenario.

## Not supported by default

- Instagram posts (the Instagram channel needs a login)
- Paid transcription with `youtube transcribe` or `xiaoyuzhou transcribe`

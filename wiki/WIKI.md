# LLMWiki Schema

## Purpose
This wiki is maintained by the LLMWiki bot. It serves as the compiled knowledge base
for a Discord server, synthesising conversations into structured, interlinked pages.

## Directory Structure
- entities/ — One page per notable person, tool, project, or concept
- topics/ — One page per recurring discussion topic
- channels/ — One page per active channel (auto-generated summaries)
- timeline/ — Weekly activity logs
- synthesis/ — Cross-cutting analysis and insight pages
- resources/ — One page per significant external resource shared in the server

## Page Format
All pages use YAML frontmatter with at minimum: title, type, created, updated.

## Resource Page Naming
- resources/ → yt_{video_id}.md, gh_{owner}_{repo}.md, article_{slug}.md, tweet_{id}.md

## Entity Page Naming
- entities/ → person_{name}.md, tool_{name}.md, project_{name}.md

## Topic Page Naming
- topics/ → topic_{slug}.md

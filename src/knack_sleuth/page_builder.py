"""
Page builder for converting impact analysis markdown to reviewable HTML pages.

Converts impact analysis markdown output into styled, navigable HTML pages
for easier review and sharing.
"""

from pathlib import Path
from typing import Optional
import markdown2
import json


class ImpactAnalysisPageBuilder:
    """Build HTML pages from impact analysis markdown."""
    
    # Default CSS styling
    DEFAULT_CSS = """
    <style>
        * { margin: 0; padding: 0; box-sizing: border-box; }
        
        body {
            font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Helvetica, Arial, sans-serif;
            line-height: 1.6;
            color: #24292e;
            background: #f6f8fa;
            padding: 20px;
        }
        
        .container {
            max-width: 1200px;
            margin: 0 auto;
            background: white;
            border-radius: 8px;
            box-shadow: 0 1px 3px rgba(0,0,0,0.12), 0 1px 2px rgba(0,0,0,0.24);
            padding: 40px;
        }
        
        h1 {
            font-size: 2.5em;
            border-bottom: 3px solid #0366d6;
            padding-bottom: 10px;
            margin-bottom: 20px;
            color: #0366d6;
        }
        
        h2 {
            font-size: 1.8em;
            margin-top: 30px;
            margin-bottom: 15px;
            color: #24292e;
            border-bottom: 1px solid #e1e4e8;
            padding-bottom: 8px;
        }
        
        h3 {
            font-size: 1.4em;
            margin-top: 20px;
            margin-bottom: 10px;
            color: #586069;
        }
        
        p, ul, ol {
            margin-bottom: 15px;
        }
        
        ul, ol {
            padding-left: 30px;
        }
        
        li {
            margin-bottom: 8px;
        }
        
        code {
            background: #f6f8fa;
            padding: 2px 6px;
            border-radius: 3px;
            font-family: 'SFMono-Regular', Consolas, 'Liberation Mono', Menlo, monospace;
            font-size: 0.9em;
            color: #d73a49;
        }
        
        pre {
            background: #f6f8fa;
            padding: 16px;
            border-radius: 6px;
            overflow-x: auto;
            margin-bottom: 15px;
        }
        
        pre code {
            background: none;
            padding: 0;
            color: #24292e;
        }
        
        strong {
            font-weight: 600;
            color: #24292e;
        }
        
        .metadata {
            background: #f6f8fa;
            border-left: 4px solid #0366d6;
            padding: 15px;
            margin-bottom: 30px;
            border-radius: 4px;
        }
        
        .metadata p {
            margin-bottom: 5px;
        }
        
        .risk-badge {
            display: inline-block;
            padding: 4px 12px;
            border-radius: 12px;
            font-size: 0.85em;
            font-weight: 600;
            margin-left: 10px;
        }
        
        .risk-none { background: #28a745; color: white; }
        .risk-low { background: #ffd33d; color: #24292e; }
        .risk-medium { background: #f9826c; color: white; }
        .risk-high { background: #d73a49; color: white; }
        
        .section-count {
            color: #586069;
            font-size: 0.9em;
            font-weight: normal;
        }
        
        .empty-section {
            color: #6a737d;
            font-style: italic;
            margin-left: 20px;
        }
        
        .toc {
            background: #f6f8fa;
            border: 1px solid #e1e4e8;
            border-radius: 6px;
            padding: 20px;
            margin-bottom: 30px;
        }
        
        .toc h2 {
            margin-top: 0;
            font-size: 1.2em;
            border: none;
        }
        
        .toc ul {
            list-style: none;
            padding-left: 0;
        }
        
        .toc li {
            margin-bottom: 5px;
        }
        
        .toc a {
            color: #0366d6;
            text-decoration: none;
        }
        
        .toc a:hover {
            text-decoration: underline;
        }
        
        .footer {
            margin-top: 40px;
            padding-top: 20px;
            border-top: 1px solid #e1e4e8;
            text-align: center;
            color: #6a737d;
            font-size: 0.9em;
        }
        
        @media (max-width: 768px) {
            .container {
                padding: 20px;
            }
            h1 { font-size: 2em; }
            h2 { font-size: 1.5em; }
            h3 { font-size: 1.2em; }
        }
    </style>
    """
    
    def __init__(self, custom_css: Optional[str] = None):
        """
        Initialize the page builder.
        
        Args:
            custom_css: Optional custom CSS to override or extend default styles
        """
        self.custom_css = custom_css
    
    def build_from_markdown_file(
        self, 
        markdown_file: Path, 
        output_file: Optional[Path] = None,
        title: Optional[str] = None,
        include_toc: bool = True
    ) -> str:
        """
        Build HTML page from impact analysis markdown file.
        
        Args:
            markdown_file: Path to markdown file
            output_file: Optional path to save HTML output
            title: Optional custom title for the HTML page
            include_toc: Whether to include a table of contents
            
        Returns:
            HTML content as string
        """
        with markdown_file.open('r') as f:
            markdown_content = f.read()
        
        html = self.build_from_markdown(
            markdown_content, 
            title=title or markdown_file.stem,
            include_toc=include_toc
        )
        
        if output_file:
            with output_file.open('w') as f:
                f.write(html)
        
        return html
    
    def build_from_markdown(
        self, 
        markdown_content: str, 
        title: Optional[str] = None,
        include_toc: bool = True
    ) -> str:
        """
        Build HTML page from markdown content.
        
        Args:
            markdown_content: Markdown content string
            title: Optional page title
            include_toc: Whether to include a table of contents
            
        Returns:
            Complete HTML page as string
        """
        # Convert markdown to HTML
        html_content = markdown2.markdown(
            markdown_content,
            extras=["fenced-code-blocks", "tables", "header-ids"]
        )
        
        # Extract title from first h1 if not provided
        if not title:
            import re
            h1_match = re.search(r'<h1[^>]*>([^<]+)</h1>', html_content)
            title = h1_match.group(1) if h1_match else "Impact Analysis"
        
        # Add risk badges to risk assessment section
        html_content = self._enhance_risk_badges(html_content)
        
        # Build TOC if requested
        toc_html = ""
        if include_toc:
            toc_html = self._build_toc(html_content)
        
        # Combine into full page
        css = self.custom_css if self.custom_css else self.DEFAULT_CSS
        
        html_page = f"""<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>{title}</title>
    {css}
</head>
<body>
    <div class="container">
        {toc_html}
        {html_content}
        <div class="footer">
            <p>Generated by KnackSleuth Impact Analysis</p>
        </div>
    </div>
</body>
</html>"""
        
        return html_page
    
    def _enhance_risk_badges(self, html_content: str) -> str:
        """Add visual badges for risk levels."""
        import re
        
        # Find breaking change likelihood mentions and add badges
        patterns = {
            r'<strong>Breaking Change Likelihood:</strong> (none)': r'<strong>Breaking Change Likelihood:</strong> <span class="risk-badge risk-none">\1</span>',
            r'<strong>Breaking Change Likelihood:</strong> (low)': r'<strong>Breaking Change Likelihood:</strong> <span class="risk-badge risk-low">\1</span>',
            r'<strong>Breaking Change Likelihood:</strong> (medium)': r'<strong>Breaking Change Likelihood:</strong> <span class="risk-badge risk-medium">\1</span>',
            r'<strong>Breaking Change Likelihood:</strong> (high)': r'<strong>Breaking Change Likelihood:</strong> <span class="risk-badge risk-high">\1</span>',
        }
        
        for pattern, replacement in patterns.items():
            html_content = re.sub(pattern, replacement, html_content, flags=re.IGNORECASE)
        
        return html_content
    
    def _build_toc(self, html_content: str) -> str:
        """Build a table of contents from HTML headers."""
        import re
        
        # Extract h2 headers with IDs
        headers = re.findall(r'<h2[^>]*id="([^"]*)"[^>]*>([^<]+)</h2>', html_content)
        
        if not headers:
            return ""
        
        toc_items = []
        for header_id, header_text in headers:
            toc_items.append(f'<li><a href="#{header_id}">{header_text}</a></li>')
        
        toc_html = f"""
        <div class="toc">
            <h2>Table of Contents</h2>
            <ul>
                {''.join(toc_items)}
            </ul>
        </div>
        """
        
        return toc_html
    
    def build_from_json_analysis(
        self,
        json_file: Path,
        output_file: Optional[Path] = None,
        include_toc: bool = True
    ) -> str:
        """
        Build HTML page directly from JSON impact analysis output.
        
        Args:
            json_file: Path to JSON impact analysis file
            output_file: Optional path to save HTML output
            include_toc: Whether to include a table of contents
            
        Returns:
            Complete HTML page as string
        """
        with json_file.open('r') as f:
            analysis = json.load(f)
        
        # Convert JSON to markdown format first
        markdown_content = self._json_to_markdown(analysis)
        
        return self.build_from_markdown(
            markdown_content,
            title=f"Impact Analysis: {analysis['target']['name']}",
            include_toc=include_toc
        )
    
    def _json_to_markdown(self, analysis: dict) -> str:
        """Convert JSON analysis to markdown format."""
        md_lines = [
            f"# Impact Analysis: {analysis['target']['name']}",
            "",
            f"**Type:** {analysis['target']['type']}  ",
            f"**Key:** `{analysis['target']['key']}`  ",
            f"**Description:** {analysis['target']['description']}  ",
            "",
            "## Risk Assessment",
            "",
            f"- **Breaking Change Likelihood:** {analysis['risk_assessment']['breaking_change_likelihood']}",
            f"- **Impact Score:** {analysis['risk_assessment']['impact_score']}",
            f"- **Affected Workflows:** {', '.join(analysis['risk_assessment']['affected_user_workflows']) or 'None'}",
            "",
            "## Direct Impacts",
            "",
            f"### Connections ({len(analysis['direct_impacts']['connections'])})",
        ]
        
        for conn in analysis['direct_impacts']['connections']:
            md_lines.append(f"- {conn['description']}")
        if not analysis['direct_impacts']['connections']:
            md_lines.append("*No connection impacts*")
        
        md_lines.append("")
        md_lines.append(f"### Views ({len(analysis['direct_impacts']['views'])})")
        for view in analysis['direct_impacts']['views']:
            md_lines.append(
                f"- **{view['view_name']}** (`{view['view_key']}`) - {view['view_type']} in scene {view['scene_name']}"
            )
        if not analysis['direct_impacts']['views']:
            md_lines.append("*No view impacts*")
        
        md_lines.append("")
        md_lines.append(f"### Forms ({len(analysis['direct_impacts']['forms'])})")
        for form in analysis['direct_impacts']['forms']:
            md_lines.append(f"- **{form['view_name']}** (`{form['view_key']}`)") 
        if not analysis['direct_impacts']['forms']:
            md_lines.append("*No form impacts*")
        
        md_lines.append("")
        md_lines.append(f"### Formulas ({len(analysis['direct_impacts']['formulas'])})")
        for formula in analysis['direct_impacts']['formulas']:
            md_lines.append(f"- **{formula['field_name']}** (`{formula['field_key']}`): `{formula.get('equation', 'N/A')}`")
        if not analysis['direct_impacts']['formulas']:
            md_lines.append("*No formula impacts*")
        
        md_lines.extend([
            "",
            "## Cascade Impacts",
            "",
            f"### Affected Fields ({len(analysis['cascade_impacts']['affected_fields'])})",
        ])
        
        for field in analysis['cascade_impacts']['affected_fields']:
            md_lines.append(
                f"- **{field['field_name']}** (`{field['field_key']}`) - {field['field_type']} - {field['usage_count']} usages"
            )
        if not analysis['cascade_impacts']['affected_fields']:
            md_lines.append("*No field cascade impacts*")
        
        md_lines.extend([
            "",
            f"### Affected Scenes ({len(analysis['cascade_impacts']['affected_scenes'])})",
        ])
        for scene_key in analysis['cascade_impacts']['affected_scenes']:
            scene_info = next(
                (s for s in analysis['direct_impacts']['scenes'] if s['scene_key'] == scene_key),
                None
            )
            if scene_info:
                md_lines.append(f"- **{scene_info['scene_name']}** (`{scene_key}`) - /{scene_info['scene_slug']}")
        if not analysis['cascade_impacts']['affected_scenes']:
            md_lines.append("*No scene cascade impacts*")
        
        md_lines.extend([
            "",
            "## Summary",
            "",
            f"- **Total Direct Impacts:** {analysis['metadata']['total_direct_impacts']}",
            f"- **Total Cascade Impacts:** {analysis['metadata']['total_cascade_impacts']}",
        ])
        
        return "\n".join(md_lines)


def build_page_from_file(
    input_file: Path,
    output_file: Optional[Path] = None,
    custom_css: Optional[str] = None,
    include_toc: bool = True
) -> str:
    """
    Convenience function to build HTML page from markdown or JSON file.
    
    Args:
        input_file: Path to markdown (.md) or JSON (.json) file
        output_file: Optional path to save HTML output (defaults to input_file.html)
        custom_css: Optional custom CSS styling
        include_toc: Whether to include table of contents
        
    Returns:
        HTML content as string
    """
    builder = ImpactAnalysisPageBuilder(custom_css=custom_css)
    
    if not output_file:
        output_file = input_file.with_suffix('.html')
    
    if input_file.suffix == '.json':
        return builder.build_from_json_analysis(input_file, output_file, include_toc)
    else:
        return builder.build_from_markdown_file(input_file, output_file, include_toc=include_toc)

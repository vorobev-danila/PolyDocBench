from polydocbench.sources.wikipedia import WikipediaParser


HTML = """
<html>
  <body>
    <h1 class="firstHeading">Linear regression</h1>
    <div class="mw-parser-output">
      <div class="hatnote">For other uses, see Linear regression.</div>
      <p>In <a>statistics</a>, <b>linear regression</b> is a model.</p>
      <div class="mw-heading mw-heading2"><h2 id="Formulation">Formulation <span class="mw-editsection">[edit]</span></h2></div>
      <p>Matrix notation is</p>
      <dl>
        <dd>
          <span class="mwe-math-element">
            <span class="mwe-math-mathml-inline">
              <math alttext="{\\displaystyle y=Xb}">
                <semantics>
                  <mrow><mi>y</mi></mrow>
                  <annotation encoding="application/x-tex">{\\displaystyle y=Xb}</annotation>
                </semantics>
              </math>
            </span>
          </span>
        </dd>
      </dl>
      <ul><li>First item</li><li>Second item</li></ul>
      <figure>
        <img src="//upload.wikimedia.org/example.png" alt="Example" />
        <figcaption>An example image</figcaption>
      </figure>
    </div>
  </body>
</html>
"""


def test_wikipedia_parser_extracts_hierarchy_and_elements():
    parsed = WikipediaParser().parse_html(HTML, url="https://en.wikipedia.org/wiki/Linear_regression")

    assert parsed["title"] == "Linear regression"
    assert parsed["content"][0] == {"type": "hatnote", "text": "For other uses, see Linear regression."}
    assert parsed["content"][1]["text"] == "In statistics, linear regression is a model."

    heading = parsed["content"][2]
    assert heading["type"] == "heading"
    assert heading["level"] == 2
    assert heading["text"] == "Formulation"

    nested_types = [item["type"] for item in heading["content"]]
    assert nested_types == ["paragraph", "formula", "list", "image"]
    assert heading["content"][1]["latex"] == "y=Xb"
    assert heading["content"][3]["src"] == "https://upload.wikimedia.org/example.png"

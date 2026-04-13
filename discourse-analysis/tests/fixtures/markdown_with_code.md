# Analysis Pipeline

The discourse analysis tool processes text through **multiple stages**. Each stage produces structured output that feeds into the next.

## Architecture

We designed the pipeline to be *modular* and extensible. The [documentation](https://example.com/docs) describes each component.

```python
def analyze(text):
    profile = compute_profile(text)
    return profile
```

The code above shows the basic entry point. However, there are several important considerations:

1. Performance depends on text length
2. Some features require spaCy models
3. The output is always valid JSON

## Results

There are many possible applications for this approach. It is widely acknowledged that automated discourse analysis complements but cannot replace human interpretation.

![Pipeline diagram](images/pipeline.png)

Furthermore, the system was designed with extensibility in mind. New frameworks can be added by simply creating a markdown file in the `frameworks/` directory.

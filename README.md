# quant_strategies

Flat strategy library for tested and untested strategy files.

This repository stores strategy memory. It does not run autonomous loops and it
does not evaluate strategies directly.

## Layout

```text
untested/   strategy files still under implementation
tested/     strategy files with focused behavior tests
tests/      tests for strategy timing, side, weight, and edge cases
```

Each strategy should be one Python file until it genuinely needs more structure.

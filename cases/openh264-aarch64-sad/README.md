# OpenH264: AArch64 NEON SAD optimization

[中文](README.zh-CN.md) · [Upstream commit](https://github.com/cisco/openh264/commit/6fe62b8f3fcc6bf34512be7efc7f64e91f510f02) · [PR #4041](https://github.com/cisco/openh264/pull/4041)

**Merged on October 9, 2026.** I changed the 16x8 and 16x16 SAD routines to use two independent accumulation chains while preserving exact results. A local follow-up measured **8.7% lower median time for repeated 16x16 calls**, faster in 8 of 9 pairs. The 16x8 and scattered-access results showed no clear benefit; encoder throughput was not measured.

## Results

Tested on October 28, 2026: Apple M1, Clang 21, `-O3`, merged commit versus its [immediate parent](https://github.com/cisco/openh264/commit/bb7199902306938e7e583d7bcd01be46f10e70c9). Each measurement used 100 million calls, with nine paired repetitions and alternating execution order. Values below are medians.

| Test | Before, ns/call | After, ns/call | Faster pairs |
| --- | ---: | ---: | ---: |
| 16x16, repeated block | 6.845 | 6.251 | 8/9 |
| 16x8, repeated block | 3.215 | 3.174 | 6/9 |
| 16x16, 64 scattered blocks | 25.865 | 25.636 | 6/9 |
| 16x8, 64 scattered blocks | 11.876 | 11.949 | 2/9 |

Both versions passed **4,608 exact comparisons against a C reference**, covering positive/negative strides, unaligned addresses, extreme values, and random pixels. All timing pairs also had matching output checksums. Runs were not pinned to a core; scheduling variability limits conclusions from small differences.

## Reasoning

The original code accumulates row differences into one vector, creating a serial dependency through successive `uabal/uabal2` operations. I process two rows at a time: `uabd` computes byte differences, `uaddlp/uadalp` accumulate into separate vectors, and a final addition combines them. This exposes more independent work to the processor.

Arithmetic bounds come first: for 16x16, each 16-bit accumulator lane reaches at most 8,160, and the full SAD at most 65,280. Both fit their respective types, so reordering additions introduces neither overflow nor rounding.

**Shorter dependency chains help only where that dependency matters.** Scattered access showed no clear improvement, so repeated-block gains cannot be extrapolated to encoder throughput. Performance counters would help identify the limiting costs; representative video tests are needed to establish end-to-end gains.

#include <algorithm>
#include <array>
#include <cassert>
#include <cstdint>
#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <string>
#include <vector>

#include "aom_dsp/arm/mem_neon.h"
#include "av1/common/convolve.h"

// These files contain complete functions extracted from recorded revisions.
#include "c_kernels.inc"
#include "neon_kernels.inc"

static uint64_t c_calls[3] = {};
static uint64_t neon_calls[3] = {};
static uint64_t dispatch_calls[3] = {};
static bool use_neon = true;

#define X_ARGS                                                               \
  const uint16_t *src, int src_stride, uint16_t *dst, int dst_stride, int w,   \
      int h, const InterpFilterParams *filter, int phase,                     \
      ConvolveParams *params, int bd
#define X_PASS src, src_stride, dst, dst_stride, w, h, filter, phase, params, bd
#define Y_ARGS                                                               \
  const uint16_t *src, int src_stride, uint16_t *dst, int dst_stride, int w,   \
      int h, const InterpFilterParams *filter, int phase, int bd
#define Y_PASS src, src_stride, dst, dst_stride, w, h, filter, phase, bd
#define D_ARGS                                                               \
  const uint16_t *src, int src_stride, uint16_t *dst, int dst_stride, int w,   \
      int h, const InterpFilterParams *filter_x,                              \
      const InterpFilterParams *filter_y, int phase_x, int phase_y,           \
      ConvolveParams *params, int bd
#define D_PASS                                                               \
  src, src_stride, dst, dst_stride, w, h, filter_x, filter_y, phase_x,         \
      phase_y, params, bd

static void counted_c_x(X_ARGS) {
  ++c_calls[0];
  av1_highbd_convolve_x_sr_intrabc_c(X_PASS);
}
static void counted_c_y(Y_ARGS) {
  ++c_calls[1];
  av1_highbd_convolve_y_sr_intrabc_c(Y_PASS);
}
static void counted_c_d(D_ARGS) {
  ++c_calls[2];
  av1_highbd_convolve_2d_sr_intrabc_c(D_PASS);
}
static void dispatch_x(X_ARGS) {
  ++dispatch_calls[0];
  if (use_neon) {
    ++neon_calls[0];
    av1_highbd_convolve_x_sr_intrabc_neon(X_PASS);
  } else {
    counted_c_x(X_PASS);
  }
}
static void dispatch_y(Y_ARGS) {
  ++dispatch_calls[1];
  if (use_neon) {
    ++neon_calls[1];
    av1_highbd_convolve_y_sr_intrabc_neon(Y_PASS);
  } else {
    counted_c_y(Y_PASS);
  }
}
static void dispatch_d(D_ARGS) {
  ++dispatch_calls[2];
  if (use_neon) {
    ++neon_calls[2];
    av1_highbd_convolve_2d_sr_intrabc_neon(D_PASS);
  } else {
    counted_c_d(D_PASS);
  }
}

static decltype(&av1_highbd_convolve_x_sr_intrabc_c)
    av1_highbd_convolve_x_sr_intrabc = dispatch_x;
static decltype(&av1_highbd_convolve_y_sr_intrabc_c)
    av1_highbd_convolve_y_sr_intrabc = dispatch_y;
static decltype(&av1_highbd_convolve_2d_sr_intrabc_c)
    av1_highbd_convolve_2d_sr_intrabc = dispatch_d;

// Non-IntraBC paths are outside this local facade experiment. Fail rather
// than silently supply a substitute if the extracted facade reaches one.
[[noreturn]] static void outside_contract() {
  std::fputs("unexpected non-IntraBC facade path\n", stderr);
  std::abort();
}
static void av1_highbd_convolve_2d_scale(...) { outside_contract(); }
static void highbd_convolve_2d_facade_compound(...) { outside_contract(); }
static void highbd_convolve_2d_facade_single(...) { outside_contract(); }

// Redirect calls only while compiling the unchanged facade body. The called
// C and NEON arithmetic functions above remain the complete upstream bodies.
#define av1_highbd_convolve_x_sr_intrabc_c counted_c_x
#define av1_highbd_convolve_y_sr_intrabc_c counted_c_y
#define av1_highbd_convolve_2d_sr_intrabc_c counted_c_d
#include "facade.inc"
#undef av1_highbd_convolve_x_sr_intrabc_c
#undef av1_highbd_convolve_y_sr_intrabc_c
#undef av1_highbd_convolve_2d_sr_intrabc_c

static uint32_t next_random(uint32_t &state) {
  state ^= state << 13;
  state ^= state >> 17;
  state ^= state << 5;
  return state;
}

static void fill_source(std::vector<uint16_t> &source, int stride, int bd,
                        int pattern, uint32_t &state) {
  const int maximum = (1 << bd) - 1;
  for (size_t i = 0; i < source.size(); ++i) {
    const int x = static_cast<int>(i % stride);
    const int y = static_cast<int>(i / stride);
    int value;
    switch (pattern) {
      case 0: value = 0; break;
      case 1: value = maximum; break;
      case 2: value = ((x + y) & 1) ? maximum : 0; break;
      case 3: value = (x + y) & 1; break;
      case 4: value = (13 * x + 7 * y) & maximum; break;
      case 5: value = (x & 1) && (y & 1) ? 1 : 0; break;
      case 6: value = (x & 1) && (y & 1) ? 2 : 0; break;
      case 7: value = (x & 1) && (y & 1) ? 3 : 0; break;
      case 8: value = maximum - ((x + y) & 3); break;
      default: value = next_random(state) & maximum; break;
    }
    source[i] = static_cast<uint16_t>(value);
  }
}

static uint16_t expected_pixel(const uint16_t *source, int stride, int x,
                               int y, int phase) {
  const int at = y * stride + x;
  if (phase == 0) return (source[at] + source[at + 1] + 1) >> 1;
  if (phase == 1) return (source[at] + source[at + stride] + 1) >> 1;
  return (source[at] + source[at + 1] + source[at + stride] +
          source[at + stride + 1] + 2) >> 2;
}

static void print_counts(const char *name, const uint64_t counts[3]) {
  std::printf("\"%s\":[%llu,%llu,%llu]", name,
              static_cast<unsigned long long>(counts[0]),
              static_cast<unsigned long long>(counts[1]),
              static_cast<unsigned long long>(counts[2]));
}

int main(int argc, char **argv) {
  if (argc != 3 ||
      (std::string(argv[1]) != "smoke" && std::string(argv[1]) != "full") ||
      (std::string(argv[2]) != "neon" && std::string(argv[2]) != "c")) {
    std::fprintf(stderr, "usage: %s smoke|full neon|c\n", argv[0]);
    return 2;
  }
  const bool full = std::string(argv[1]) == "full";
  use_neon = std::string(argv[2]) == "neon";
  const std::array<std::array<int, 2>, 27> sizes = {{{2, 2}, {2, 4}, {2, 8},
      {4, 2}, {4, 4}, {4, 8}, {4, 16}, {8, 2}, {8, 4}, {8, 8}, {8, 16},
      {8, 32}, {16, 4}, {16, 8}, {16, 16}, {16, 32}, {16, 64}, {32, 8},
      {32, 16}, {32, 32}, {32, 64}, {64, 16}, {64, 32}, {64, 64},
      {64, 128}, {128, 64}, {128, 128}}};
  const int smoke_sizes[] = {0, 4, 9, 14, 26};
  const int size_count = full ? static_cast<int>(sizes.size()) : 5;
  const int layout_count = full ? 3 : 1;
  const int pattern_count = full ? 13 : 6;
  uint64_t scenarios = 0, pixel_mismatches = 0, c_mismatches = 0;
  uint64_t c_differential_mismatches = 0, guard_mismatches = 0;
  uint64_t source_mismatches = 0;
  uint64_t pixels_checked = 0, guard_cells_checked = 0;
  uint64_t digest = UINT64_C(14695981039346656037);
  uint64_t output_digest = UINT64_C(14695981039346656037);
  uint32_t state = 20261118;
  const InterpFilterParams *filters[2] = {
      &av1_intrabc_filter_params, &av1_intrabc_filter_params};
  for (int s = 0; s < size_count; ++s) {
    const int index = full ? s : smoke_sizes[s];
    const int w = sizes[index][0], h = sizes[index][1];
    for (int layout = 0; layout < layout_count; ++layout) {
      const int src_stride = w + 16 + 7 * layout;
      const int dst_stride = w + 3 + 8 * layout;
      const int src_offset = layout + 1, dst_offset = 17 + 2 * layout;
      const size_t dst_size = dst_offset + (h + 2) * dst_stride + 19;
      for (int bd : {8, 10, 12}) {
        for (int pattern = 0; pattern < pattern_count; ++pattern) {
          std::vector<uint16_t> source(src_offset + (h + 3) * src_stride + 32);
          fill_source(source, src_stride, bd, pattern, state);
          const std::vector<uint16_t> source_before = source;
          for (uint16_t value : source) {
            digest ^= value & 255;
            digest *= UINT64_C(1099511628211);
            digest ^= value >> 8;
            digest *= UINT64_C(1099511628211);
          }
          const uint16_t *src = source.data() + src_offset;
          for (int phase = 0; phase < 3; ++phase) {
            ++scenarios;
            constexpr uint16_t guard = 0xa5a5;
            std::vector<uint16_t> destination(dst_size, guard);
            std::vector<uint16_t> reference(dst_size, guard);
            uint16_t *dst = destination.data() + dst_offset;
            uint16_t *ref = reference.data() + dst_offset;
            ConvolveParams params = get_conv_params(0, 0, bd);
            const int sx = phase == 1 ? 0 : 8;
            const int sy = phase == 0 ? 0 : 8;
            av1_highbd_convolve_2d_facade(
                CONVERT_TO_BYTEPTR(src), src_stride, CONVERT_TO_BYTEPTR(dst),
                dst_stride, w, h, filters, sx, 16, sy, 16, 0, &params, bd);
            if (phase == 0) {
              av1_highbd_convolve_x_sr_intrabc_c(
                  src, src_stride, ref, dst_stride, w, h, filters[0], sx,
                  &params, bd);
            } else if (phase == 1) {
              av1_highbd_convolve_y_sr_intrabc_c(
                  src, src_stride, ref, dst_stride, w, h, filters[1], sy, bd);
            } else {
              av1_highbd_convolve_2d_sr_intrabc_c(
                  src, src_stride, ref, dst_stride, w, h, filters[0], filters[1],
                  sx, sy, &params, bd);
            }
            for (size_t at = 0; at < destination.size(); ++at) {
              const auto relative = static_cast<int64_t>(at) - dst_offset;
              const bool active = relative >= 0 &&
                  relative / dst_stride < h && relative % dst_stride < w;
              if (active) {
                ++pixels_checked;
                const int x = static_cast<int>(relative % dst_stride);
                const int y = static_cast<int>(relative / dst_stride);
                const auto expected = expected_pixel(src, src_stride, x, y, phase);
                pixel_mismatches += destination[at] != expected;
                c_mismatches += reference[at] != expected;
                c_differential_mismatches += destination[at] != reference[at];
                output_digest ^= destination[at];
                output_digest *= UINT64_C(1099511628211);
              } else {
                guard_cells_checked += 2;
                guard_mismatches += destination[at] != guard;
                guard_mismatches += reference[at] != guard;
              }
            }
            source_mismatches += source != source_before;
          }
        }
      }
    }
  }
  std::printf("{\"profile\":\"%s\",\"installed_dispatch\":\"%s\","
              "\"scenarios\":%llu,\"pixel_mismatches\":%llu,"
              "\"c_formula_mismatches\":%llu,"
              "\"c_differential_mismatches\":%llu,"
              "\"guard_mismatches\":%llu,\"source_mismatches\":%llu,"
              "\"pixels_checked\":%llu,\"guard_cells_checked\":%llu,"
              "\"input_digest_fnv1a64\":\"%016llx\","
              "\"output_digest_fnv1a64\":\"%016llx\",",
              full ? "full" : "smoke", use_neon ? "neon" : "c",
              static_cast<unsigned long long>(scenarios),
              static_cast<unsigned long long>(pixel_mismatches),
              static_cast<unsigned long long>(c_mismatches),
              static_cast<unsigned long long>(c_differential_mismatches),
              static_cast<unsigned long long>(guard_mismatches),
              static_cast<unsigned long long>(source_mismatches),
              static_cast<unsigned long long>(pixels_checked),
              static_cast<unsigned long long>(guard_cells_checked),
              static_cast<unsigned long long>(digest),
              static_cast<unsigned long long>(output_digest));
  print_counts("c_calls", c_calls);
  std::putchar(',');
  print_counts("neon_calls", neon_calls);
  std::putchar(',');
  print_counts("dispatch_calls", dispatch_calls);
  std::puts("}");
  return pixel_mismatches || c_mismatches || c_differential_mismatches ||
      guard_mismatches || source_mismatches ? 1 : 0;
}

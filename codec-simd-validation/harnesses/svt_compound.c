/* Deterministic two-predictor checks for the SVT high bit-depth scaler. */
#include <inttypes.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#include "common_dsp_rtcd.h"
#include "convolve.h"
#include "inter_prediction.h"

enum { PAD = 32 };
static uint32_t random_state = 0x4a6f7931u;
static uint64_t input_hash = UINT64_C(14695981039346656037);

static void hash_word(uint32_t word) {
    for (int i = 0; i < 4; ++i) {
        input_hash ^= (word >> (8 * i)) & 255u;
        input_hash *= UINT64_C(1099511628211);
    }
}

static uint32_t next_random(void) {
    random_state ^= random_state << 13;
    random_state ^= random_state >> 17;
    random_state ^= random_state << 5;
    return random_state;
}

static uint64_t difference(const uint16_t *left, const uint16_t *right, size_t count) {
    uint64_t different = 0;
    for (size_t i = 0; i < count; ++i)
        different += left[i] != right[i];
    return different;
}

static uint64_t changed(const uint16_t *data, size_t count, uint16_t sentinel) {
    uint64_t different = 0;
    for (size_t i = 0; i < count; ++i)
        different += data[i] != sentinel;
    return different;
}

static int padding_changed(const uint16_t *data, int stride, int rows,
                           int width, int height, uint16_t sentinel) {
    for (int y = 0; y < rows; ++y)
        for (int x = 0; x < stride; ++x)
            if ((y < PAD || y >= PAD + height || x < PAD || x >= PAD + width) &&
                data[y * stride + x] != sentinel)
                return 1;
    return 0;
}

typedef struct Counts {
    uint64_t pairs, baseline_cases, baseline_mismatch_cases;
    uint64_t c_first_changed_cases, first_dst_mismatch_cases, first_dst_mismatch_cells;
    uint64_t first_compound_mismatch_cases, first_compound_mismatch_cells;
    uint64_t second_dst_mismatch_cases, second_dst_mismatch_cells;
    uint64_t second_compound_mismatch_cases, second_compound_mismatch_cells;
    uint64_t c_persistent_changed_cases, neon_persistent_changed_cases;
    uint64_t padding_changed_cases;
    int witness[9];
} Counts;

static void call_scaler(int reference, const uint16_t *src, int src_stride,
                        uint16_t *dst, int dst_stride, int w, int h,
                        const InterpFilterParams *fx, const InterpFilterParams *fy,
                        int px, int xs, int py, int ys, ConvolveParams *params, int bd) {
    if (reference)
        svt_av1_highbd_convolve_2d_scale_c(src, src_stride, dst, dst_stride, w, h,
                                         fx, fy, px, xs, py, ys, params, bd);
    else
        svt_av1_highbd_convolve_2d_scale_neon(src, src_stride, dst, dst_stride, w, h,
                                            fx, fy, px, xs, py, ys, params, bd);
}

static int run_dimensions(Counts *counts, int w, int h, int full) {
    static const int steps[][2] = {
        {512, 1024}, {1024, 512}, {1024, 1024},
        {1280, 1536}, {1536, 1280}, {2048, 2048}};
    static const int weights[][2] = {
        {0, 0}, {9, 7}, {11, 5}, {12, 4}, {13, 3},
        {7, 9}, {5, 11}, {4, 12}, {3, 13}};
    const int src_stride = (2 * w + 2 * PAD + 15) & ~15;
    const int dst_stride = src_stride + 16;
    const int rows = 2 * h + 2 * PAD;
    const size_t src_count = (size_t)rows * src_stride;
    const size_t dst_count = (size_t)rows * dst_stride;
    uint16_t *src = malloc(src_count * sizeof(*src));
    uint16_t *dst[2] = {malloc(dst_count * sizeof(**dst)), malloc(dst_count * sizeof(**dst))};
    uint16_t *compound[2] = {malloc(dst_count * sizeof(**compound)), malloc(dst_count * sizeof(**compound))};
    uint16_t *saved[2] = {malloc(dst_count * sizeof(**saved)), malloc(dst_count * sizeof(**saved))};
    if (!src || !dst[0] || !dst[1] || !compound[0] || !compound[1] || !saved[0] || !saved[1]) {
        fprintf(stderr, "allocation failed\n");
        free(src);
        for (int side = 0; side < 2; ++side) {
            free(dst[side]); free(compound[side]); free(saved[side]);
        }
        return 0;
    }
    for (int bd = 10; bd <= 12; bd += 2) {
        for (int step = 0; step < (full ? 6 : 2); ++step) {
            const int selected_step = full ? step : step * 5;
            const int xs = steps[selected_step][0], ys = steps[selected_step][1];
            for (int fy_id = 0; fy_id < SWITCHABLE_FILTERS; ++fy_id) {
                const InterpFilterParams fy = av1_get_interp_filter_params_with_block_size((InterpFilter)fy_id, h);
                for (int fx_id = 0; fx_id < SWITCHABLE_FILTERS; ++fx_id) {
                    const InterpFilterParams fx = av1_get_interp_filter_params_with_block_size((InterpFilter)fx_id, w);
                    for (int weight = 0; weight < 9; ++weight) {
                        for (int phase = 0; phase < 3; ++phase) {
                            int px = phase == 0 ? 0 : phase == 1 ? SCALE_SUBPEL_MASK : (int)(next_random() & SCALE_SUBPEL_MASK);
                            int py = phase == 0 ? 0 : phase == 1 ? SCALE_SUBPEL_MASK : (int)(next_random() & SCALE_SUBPEL_MASK);
                            for (size_t i = 0; i < src_count; ++i) {
                                src[i] = (uint16_t)(next_random() & ((1u << bd) - 1));
                                hash_word(src[i]);
                            }
                            const int inputs[] = {w, h, bd, xs, ys, fx_id, fy_id, weight, px, py};
                            for (size_t i = 0; i < sizeof(inputs) / sizeof(*inputs); ++i)
                                hash_word((uint32_t)inputs[i]);
                            ConvolveParams params[2];
                            for (int side = 0; side < 2; ++side) {
                                for (size_t i = 0; i < dst_count; ++i) {
                                    dst[side][i] = UINT16_MAX;
                                    compound[side][i] = 0x5a5a;
                                }
                                params[side] = get_conv_params_no_round(0, compound[side] + PAD * dst_stride + PAD, dst_stride, 1, bd);
                                params[side].use_dist_wtd_comp_avg = weight != 0;
                                params[side].fwd_offset = weights[weight][0];
                                params[side].bck_offset = weights[weight][1];
                                call_scaler(side == 0, src + PAD * src_stride + PAD, src_stride,
                                            dst[side] + PAD * dst_stride + PAD, dst_stride,
                                            w, h, &fx, &fy, px, xs, py, ys, &params[side], bd);
                                memcpy(saved[side], compound[side], dst_count * sizeof(**compound));
                            }
                            ++counts->pairs;
                            counts->c_first_changed_cases += changed(dst[0], dst_count, UINT16_MAX) != 0;
                            uint64_t count = difference(dst[0], dst[1], dst_count);
                            counts->first_dst_mismatch_cases += count != 0;
                            counts->first_dst_mismatch_cells += count;
                            if (count && counts->first_dst_mismatch_cases == 1) {
                                const int witness[] = {w, h, bd, xs, ys, fx_id, fy_id, px, py};
                                memcpy(counts->witness, witness, sizeof(witness));
                            }
                            count = difference(compound[0], compound[1], dst_count);
                            counts->first_compound_mismatch_cases += count != 0;
                            counts->first_compound_mismatch_cells += count;
                            int guard_failure = 0;
                            for (int side = 0; side < 2; ++side)
                                guard_failure |= padding_changed(dst[side], dst_stride, rows, w, h, UINT16_MAX) |
                                    padding_changed(compound[side], dst_stride, rows, w, h, 0x5a5a);
                            px ^= SCALE_SUBPEL_MASK;
                            py ^= SCALE_SUBPEL_MASK;
                            for (int side = 0; side < 2; ++side) {
                                params[side].do_average = 1;
                                call_scaler(side == 0, src + PAD * src_stride + PAD, src_stride,
                                            dst[side] + PAD * dst_stride + PAD, dst_stride,
                                            w, h, &fx, &fy, px, xs, py, ys, &params[side], bd);
                                guard_failure |= padding_changed(dst[side], dst_stride, rows, w, h, UINT16_MAX) |
                                    padding_changed(compound[side], dst_stride, rows, w, h, 0x5a5a);
                            }
                            counts->padding_changed_cases += guard_failure != 0;
                            count = difference(dst[0], dst[1], dst_count);
                            counts->second_dst_mismatch_cases += count != 0;
                            counts->second_dst_mismatch_cells += count;
                            count = difference(compound[0], compound[1], dst_count);
                            counts->second_compound_mismatch_cases += count != 0;
                            counts->second_compound_mismatch_cells += count;
                            counts->c_persistent_changed_cases += difference(compound[0], saved[0], dst_count) != 0;
                            counts->neon_persistent_changed_cases += difference(compound[1], saved[1], dst_count) != 0;
                            if (weight == 0) {
                                for (int side = 0; side < 2; ++side) {
                                    for (size_t i = 0; i < dst_count; ++i)
                                        dst[side][i] = UINT16_MAX;
                                    params[side] = get_conv_params_no_round(0, NULL, 0, 0, bd);
                                    call_scaler(side == 0, src + PAD * src_stride + PAD, src_stride,
                                                dst[side] + PAD * dst_stride + PAD, dst_stride,
                                                w, h, &fx, &fy, px, xs, py, ys, &params[side], bd);
                                }
                                ++counts->baseline_cases;
                                counts->baseline_mismatch_cases += difference(dst[0], dst[1], dst_count) != 0;
                            }
                        }
                    }
                }
            }
        }
    }
    free(src);
    for (int side = 0; side < 2; ++side) {
        free(dst[side]); free(compound[side]); free(saved[side]);
    }
    return 1;
}

int main(int argc, char **argv) {
    static const int dimensions[][2] = {
        {2, 2}, {2, 4}, {4, 4}, {4, 8}, {8, 4}, {8, 8},
        {8, 16}, {16, 8}, {16, 16}, {16, 32}, {32, 16}, {32, 32},
        {32, 64}, {64, 32}, {64, 64}, {64, 128}, {128, 64}, {128, 128}};
    if (argc != 2 || (strcmp(argv[1], "smoke") != 0 && strcmp(argv[1], "full") != 0)) {
        fprintf(stderr, "usage: %s smoke|full\n", argv[0]);
        return 2;
    }
    const int full = strcmp(argv[1], "full") == 0;
    Counts counts = {0};
    for (int block = 0; block < (full ? 18 : 4); ++block) {
        const int selected = full ? block : block * 3;
        if (!run_dimensions(&counts, dimensions[selected][0], dimensions[selected][1], full))
            return 3;
    }
    printf("{\n  \"profile\": \"%s\",\n  \"seed\": 1248819505,\n", argv[1]);
    printf("  \"input_digest_fnv1a64\": \"%016" PRIx64 "\",\n", input_hash);
#define PRINT_COUNT(name) printf("  \"" #name "\": %" PRIu64 ",\n", counts.name)
    PRINT_COUNT(pairs);
    PRINT_COUNT(baseline_cases);
    PRINT_COUNT(baseline_mismatch_cases);
    PRINT_COUNT(c_first_changed_cases);
    PRINT_COUNT(first_dst_mismatch_cases);
    PRINT_COUNT(first_dst_mismatch_cells);
    PRINT_COUNT(first_compound_mismatch_cases);
    PRINT_COUNT(first_compound_mismatch_cells);
    PRINT_COUNT(second_dst_mismatch_cases);
    PRINT_COUNT(second_dst_mismatch_cells);
    PRINT_COUNT(second_compound_mismatch_cases);
    PRINT_COUNT(second_compound_mismatch_cells);
    PRINT_COUNT(c_persistent_changed_cases);
    PRINT_COUNT(neon_persistent_changed_cases);
    PRINT_COUNT(padding_changed_cases);
#undef PRINT_COUNT
    printf("  \"first_dst_witness\": [%d,%d,%d,%d,%d,%d,%d,%d,%d]\n}\n",
           counts.witness[0], counts.witness[1], counts.witness[2],
           counts.witness[3], counts.witness[4], counts.witness[5],
           counts.witness[6], counts.witness[7], counts.witness[8]);
    return 0;
}

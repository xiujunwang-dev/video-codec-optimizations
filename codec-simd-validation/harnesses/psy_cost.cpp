#include "kernel.hpp"
#include <array>
#include <cerrno>
#include <chrono>
#include <cstdint>
#include <cstdlib>
#include <iostream>
#include <limits>
#include <string>
#include <vector>

using Block = std::array<uint16_t, 16>;

static int energy(const Block &block)
{
    std::array<int64_t, 16> t{};
    int64_t total = 0;
    for (int i = 0; i < 16; ++i) { t[i] = block[i]; total += block[i]; }
    for (int step = 1; step < 16; step *= 2)
        for (int group = 0; group < 16; group += 2 * step)
            for (int j = 0; j < step; ++j) {
                const auto a = t[group+j], b = t[group+j+step];
                t[group+j] = a+b; t[group+j+step] = a-b;
            }
    int64_t sum = 0;
    for (auto x : t) sum += std::llabs(x);
    return int((sum >> 1) - (total >> 2));
}

static int matrix_energy(const Block &block)
{
    int64_t sum = 0, total = 0;
    for (auto v : block) total += v;
    for (unsigned row = 0; row < 16; ++row) {
        int64_t coefficient = 0;
        for (unsigned col = 0; col < 16; ++col) {
            unsigned v = row & col, parity = 0;
            while (v) { parity ^= v & 1; v >>= 1; }
            coefficient += parity ? -int64_t(block[col]) : int64_t(block[col]);
        }
        sum += std::llabs(coefficient);
    }
    return int((sum >> 1) - (total >> 2));
}

struct Rng {
    uint32_t state;
    uint32_t next() { state ^= state << 13; state ^= state >> 17; state ^= state << 5; return state; }
};
static void print_block(const Block &b) {
    std::cout << '[';
    for (int i=0;i<16;++i) { if(i) std::cout << ','; std::cout << b[i]; }
    std::cout << ']';
}
struct Stats {
    uint64_t count=0, source_errors=0, recon_errors=0, cost_errors=0, memory_errors=0, oracle_errors=0;
    uint64_t hash=14695981039346656037ULL;
    int64_t first=-1;
    Block source{}, recon{};
    int expected=0, observed=0, es=0, er=0, os=0, ore=0;
    void byte(uint8_t b) { hash ^= b; hash *= 1099511628211ULL; }
    void test(const Block &s, const Block &r) {
        const int stride = std::array<int,3>{4,7,16}[count%3];
        const int offset = std::array<int,3>{0,1,3}[(count/3)%3];
        std::vector<uint16_t> sb(offset+4*stride+16,0xa55a), rb(sb.size(),0xa55a);
        for(int y=0;y<4;++y) for(int x=0;x<4;++x) { sb[offset+y*stride+x]=s[y*4+x]; rb[offset+y*stride+x]=r[y*4+x]; }
        const auto scopy=sb, rcopy=rb;
        const int se=energy(s), re=energy(r);
        if(count<32 && (se!=matrix_energy(s) || re!=matrix_energy(r))) ++oracle_errors;
        const int so=candidate::calc_energy_4x4(sb.data()+offset,stride);
        const int ro=candidate::calc_energy_4x4(rb.data()+offset,stride);
        const int e=std::abs(se-re), o=std::abs(so-ro);
        source_errors += se!=so; recon_errors += re!=ro; cost_errors += e!=o;
        memory_errors += sb!=scopy || rb!=rcopy;
        for(auto b : s) { byte(b & 255); byte(b>>8); }
        for(auto b : r) { byte(b & 255); byte(b>>8); }
        byte(stride); byte(offset);
        if(first<0 && e!=o) { first=count; source=s; recon=r; expected=e; observed=o; es=se; er=re; os=so; ore=ro; }
        ++count;
    }
    void emit(const std::string &group,int depth,uint32_t seed,double seconds) {
        std::cout << "{\"group\":\"" << group << "\",\"depth\":" << depth << ",\"seed\":" << seed
        << ",\"cases\":" << count << ",\"source_energy_mismatches\":" << source_errors
        << ",\"recon_energy_mismatches\":" << recon_errors << ",\"cost_mismatches\":" << cost_errors
        << ",\"input_mutations\":" << memory_errors << ",\"oracle_disagreements\":" << oracle_errors
        << ",\"input_fnv1a64\":\"" << std::hex << hash << std::dec << "\",\"elapsed_seconds\":" << seconds
        << ",\"first_failure_index\":" << first;
        if(first>=0) {
            std::cout << ",\"witness\":{\"source\":"; print_block(source);
            std::cout << ",\"recon\":"; print_block(recon);
            std::cout << ",\"expected_cost\":" << expected << ",\"observed_cost\":" << observed
            << ",\"expected_source_energy\":" << es << ",\"observed_source_energy\":" << os
            << ",\"expected_recon_energy\":" << er << ",\"observed_recon_energy\":" << ore << '}';
        }
        std::cout << "}\n";
    }
};
struct Options {
    unsigned cases=4096, exhaustive_limit=65536;
    std::vector<uint32_t> seeds{1u,17u,20261117u};
};

static bool parse_unsigned(const std::string &text,uint64_t maximum,uint64_t &value) {
    if(text.empty() || text.find_first_not_of("0123456789")!=std::string::npos) return false;
    errno=0;
    char *end=nullptr;
    const auto parsed=std::strtoull(text.c_str(),&end,10);
    if(errno==ERANGE || end==text.c_str() || *end || parsed==0 || parsed>maximum) return false;
    value=parsed;
    return true;
}

static bool parse_options(int argc,char **argv,Options &options) {
    bool explicit_seeds=false;
    for(int i=1;i<argc;++i) {
        const std::string option=argv[i];
        if(option=="--help") {
            std::cout << "Usage: psy_cost [--cases 1..16777216] [--exhaustive-limit 1..65536] [--seed 1..4294967295]...\n";
            std::exit(0);
        }
        if(option!="--cases" && option!="--exhaustive-limit" && option!="--seed") {
            std::cerr << "Unknown option: " << option << '\n';
            return false;
        }
        if(i+1==argc) {
            std::cerr << "Missing integer value for " << option << '\n';
            return false;
        }
        uint64_t value=0;
        const uint64_t maximum=option=="--cases"?16777216ULL:option=="--exhaustive-limit"?65536ULL:std::numeric_limits<uint32_t>::max();
        if(!parse_unsigned(argv[++i],maximum,value)) {
            std::cerr << "Invalid positive integer for " << option << '\n';
            return false;
        }
        if(option=="--cases") options.cases=static_cast<unsigned>(value);
        else if(option=="--exhaustive-limit") options.exhaustive_limit=static_cast<unsigned>(value);
        else {
            if(!explicit_seeds) { options.seeds.clear(); explicit_seeds=true; }
            for(const auto seed : options.seeds) if(seed==value) {
                std::cerr << "Duplicate seed: " << value << '\n';
                return false;
            }
            options.seeds.push_back(static_cast<uint32_t>(value));
        }
    }
    return true;
}

static void run(const std::string &group,int depth,uint32_t seed,const Options &options) {
    const auto start=std::chrono::steady_clock::now();
    Stats stats; Rng rng{seed}; Block s{},r{};
    const uint16_t maximum=(1u<<depth)-1;
    if(group=="known-witness") {
        s={4095,0,4095,0,0,0,0,0,0,0,4095,4095,0,4095,4095,0};
        if(energy(s)!=67568 || matrix_energy(s)!=67568) std::exit(3);
        stats.test(s,r);
    } else if(group.rfind("exhaustive-",0)==0) {
        for(unsigned mask=0;mask<options.exhaustive_limit;++mask) {
            for(int j=0;j<16;++j) {
                s[j]=(mask>>j&1)?maximum:0;
                r[j]=group=="exhaustive-zero"?0:group=="exhaustive-complement"?maximum-s[j]:s[j]?maximum-1:1;
            }
            stats.test(s,r);
        }
    } else {
        for(unsigned i=0;i<options.cases;++i) {
            for(int j=0;j<16;++j) {
                const uint32_t a=rng.next(), b=rng.next();
                s[j]=group=="uniform-independent"?(a&maximum):(a&1)?maximum:0;
                r[j]=group=="uniform-independent"?(b&maximum):group=="endpoints-zero"?0:s[j]?maximum-1:1;
            }
            stats.test(s,r);
        }
    }
    stats.emit(group,depth,seed,std::chrono::duration<double>(std::chrono::steady_clock::now()-start).count());
    if(stats.oracle_errors || stats.memory_errors) std::exit(4);
}
int main(int argc,char **argv) {
    Options options;
    if(!parse_options(argc,argv,options)) return 2;
    run("known-witness",12,1,options);
    for(int depth : {10,12}) {
        for(uint32_t seed : options.seeds)
            for(const auto &group : {"uniform-independent","endpoints-zero","endpoints-near"}) run(group,depth,seed,options);
        for(const auto &group : {"exhaustive-zero","exhaustive-complement","exhaustive-near"}) run(group,depth,1,options);
    }
}

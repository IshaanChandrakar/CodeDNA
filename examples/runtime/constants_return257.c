// The harness must observe 257, not the low-byte process exit status 1.
int main(void) {
    int base = 16 * 16;
    return base + 1;
}

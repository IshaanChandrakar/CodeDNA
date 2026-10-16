int main(void) {
    int start = 1 + 1;
    int limit = 2 * 3;
    int total = 0;
    int i;
    for (i = start; i < limit; i = i + 1) {
        total = total + i;
    }
    return total * 10 + i;
}

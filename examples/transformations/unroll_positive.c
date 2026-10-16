int main(void) {
    int total = 0;
    int i;
    for (i = 0; i < 4; i = i + 1) {
        total = total + i;
    }
    return total * 10 + i;
}

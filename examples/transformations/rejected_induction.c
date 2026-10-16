int main(void) {
    int total = 0;
    for (int i = 0; i < 4; i = i + 1) {
        total = total + i;
        i = i + 2;
    }
    return total;
}

int main(void) {
    int total = 0;
    for (int i = 0; i < 3; i = i + 1) {
        for (int j = 0; j < 2; j = j + 1) {
            total = total + i * j;
        }
    }
    return total;
}

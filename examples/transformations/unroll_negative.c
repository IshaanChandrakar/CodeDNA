int main(void) {
    int total = 0;
    int i;
    for (i = 5; i > 0; i = i - 2) {
        total = total + i;
    }
    return total * 10 + i;
}

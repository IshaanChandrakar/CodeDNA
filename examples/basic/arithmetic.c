int main(void) {
    int x = 2 + 3 * 4;
    int y;
    y = (x - 2) / 3;
    x = x + y % 3;
    return x;
}

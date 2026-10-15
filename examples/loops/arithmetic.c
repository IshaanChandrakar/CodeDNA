int main() {
    int total = 0;
    int i;
    for (i = 1; i <= 5; i = i + 1) {
        total = total + (i * (i + 2) - 1) % 7;
    }
    return total;
}

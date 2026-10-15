int main(void) {
    int first = 2;
    int second = 3;
    if (first != 0)
        if (second == 3)
            first = first + second;
        else
            first = first - second;
    return first;
}
